"""Native WebKit bridge fixture: no production data, model, identity or MCP calls."""

import asyncio
import json
import os
import site
import sys
import signal
import threading
from pathlib import Path

site.addsitedir(str(Path(sys.argv[1]) / "packages"))

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import HTMLResponse, StreamingResponse

app = FastAPI()
state = {"active": False, "turn": 0, "pending": None, "messages": [], "task": None}


def log(value):
    with (Path(os.environ["OCTOP_HOME"]) / "fixture-calls.jsonl").open("a") as out:
        out.write(json.dumps(value, ensure_ascii=False) + "\n")


def auth(token):
    if token != "Bearer fixture-only-token":
        raise HTTPException(401)


@app.get("/api/health")
async def health():
    return {"ok": True, "fixture": True}


@app.get("/api/health/companion")
async def identity():
    return {"companion": True, "instance": os.environ["OCTOP_COMPANION_INSTANCE"]}


@app.get("/login")
async def login():
    return HTMLResponse(
        "<h1>隔离测试登录</h1><p>仅模拟账号，不访问企业服务。</p><button onclick=\"localStorage.setItem('auth_token','fixture-only-token')\">登录隔离测试账号</button>"
    )


@app.get("/api/auth/me")
async def me(authorization: str = Header(default="")):
    auth(authorization)
    return {"id": 901, "username": "native-fixture", "display_name": "隔离测试", "role": "user"}


@app.get("/api/companion/access")
async def access(authorization: str = Header(default="")):
    auth(authorization)
    return {"allowed": True}


@app.get("/api/companion/agents")
async def agents(authorization: str = Header(default="")):
    auth(authorization)
    return [{"agent_id": "owned", "name": "售后质量专家", "user_id": 901, "is_running": True}]


@app.get("/api/connector-instances")
async def connections(authorization: str = Header(default="")):
    auth(authorization)
    return [{"mcp_server_name": "aftersales_quality", "display_name": "隔离连接器", "usable": True}]


@app.get("/api/knowledge-bases")
async def knowledge(authorization: str = Header(default="")):
    auth(authorization)
    return []


@app.get("/api/agents/owned/threads/{thread}/history")
async def history(thread: str, authorization: str = Header(default="")):
    auth(authorization)
    return {
        "messages": state["messages"],
        "turn_active": state["active"],
        "hitl_pending": state["pending"],
        "awaiting_user": bool(state["pending"]),
    }


@app.post("/api/agents/owned/upload")
async def upload(file: UploadFile, authorization: str = Header(default="")):
    auth(authorization)
    log({"upload": file.filename, "size": len(await file.read())})
    return {
        "path": "inbound/" + file.filename,
        "filename": file.filename,
        "media_type": file.content_type,
    }


@app.websocket("/api/agents/owned/chat/ws")
async def chat(ws: WebSocket):
    auth(ws.headers.get("authorization"))
    await ws.accept()

    async def emit(frame):
        await ws.send_json({"thread_id": "native-thread", **frame})

    async def run(text):
        state["active"] = True
        state["turn"] += 1
        turn = "turn-" + str(state["turn"])
        await emit({"type": "turn.started", "turn_id": turn})
        try:
            if "审批" in text or "追问" in text:
                action = (
                    {
                        "name": "ask_user_question",
                        "args": {
                            "questions": [
                                {
                                    "question": "需要分析哪一周？",
                                    "options": [{"label": "本周"}, {"label": "上周"}],
                                }
                            ]
                        },
                    }
                    if "追问" in text
                    else {
                        "name": "fixture.read",
                        "description": "读取隔离样例",
                        "args": {"scope": "本次测试"},
                    }
                )
                state["pending"] = {
                    "pending_id": ("delayed-" if "慢" in text else "pending-") + str(state["turn"]),
                    "action_requests": [action],
                }
                await emit({"type": "hitl_required", "request": state["pending"]})
                state["active"] = False
                await emit({"type": "turn.ended", "turn_id": turn, "hitl_paused": True})
                return
            await emit(
                {"type": "tool_call_chunk", "name": "fixture.read", "display_name": "隔离查询"}
            )
            await asyncio.sleep(3)
            for n in range(8):
                await emit({"type": "token", "content": f"隔离回答{n + 1}。"})
                await asyncio.sleep(0.8)
        except asyncio.CancelledError:
            pass
        finally:
            if not state["pending"]:
                state["active"] = False
                await emit({"type": "done"})
                await emit({"type": "turn.ended", "turn_id": turn})

    try:
        while True:
            frame = await ws.receive_json()
            log(frame)
            kind = frame.get("type")
            if kind == "user_turn":
                if frame.get("delivery") == "steer":
                    await emit(
                        {
                            "type": "steer.ack",
                            "status": "queued",
                            "turn_id": "turn-" + str(state["turn"]),
                            "client_pending_id": frame["client_pending_id"],
                            "pending_id": "native-steer",
                        }
                    )
                    continue
                state["messages"].extend(frame.get("messages", []))
                text = " ".join(
                    b.get("text", "")
                    for m in frame.get("messages", [])
                    for b in m.get("content", [])
                    if b.get("type") == "text"
                )
                state["task"] = asyncio.create_task(run(text))
            elif kind == "cancel":
                if state["task"] and not state["task"].done():
                    state["task"].cancel()
                else:
                    state["active"] = False
                    await emit({"type": "done"})
            elif kind == "steer_remove":
                await emit(
                    {
                        "type": "steer.removed",
                        "client_pending_id": frame["client_pending_id"],
                        "pending_id": frame["pending_id"],
                    }
                )
            elif kind == "subscribe":
                await emit({"type": "turn_status", "active": state["active"]})
                if state["pending"]:
                    await emit(
                        {
                            "type": "turn.resumed",
                            "turn_id": "turn-" + str(state["turn"]),
                            "phase": "hitl_paused",
                        }
                    )
            elif kind == "ping":
                await emit({"type": "pong"})
    except Exception:
        pass


@app.post("/api/agents/owned/chat/hitl/resume")
async def resume(request: Request, authorization: str = Header(default="")):
    auth(authorization)
    body = await request.json()
    log({"resume": body})
    assert state["pending"] and body["pending_id"] == state["pending"]["pending_id"]
    assert "hitl_policy" not in body
    if body["pending_id"].startswith("delayed-"):
        await asyncio.sleep(2)
    state["pending"] = None

    async def events():
        state["active"] = True
        try:
            for frame in [
                {"type": "turn.resumed", "turn_id": "turn-" + str(state["turn"])},
                {"type": "token", "content": "原生确认已收到，隔离任务继续完成。"},
                {"type": "done"},
            ]:
                yield "event: chunk\ndata: " + json.dumps(frame, ensure_ascii=False) + "\n\n"
                await asyncio.sleep(0.1)
        finally:
            state["active"] = False

    return StreamingResponse(events(), media_type="text/event-stream")


if __name__ == "__main__":
    if os.getpgrp() != os.getpid():
        os.setsid()

    def parent_lifetime():
        sys.stdin.buffer.read()
        os.killpg(os.getpgrp(), signal.SIGTERM)

    threading.Thread(target=parent_lifetime, daemon=True).start()
    uvicorn.run(
        app, host="127.0.0.1", port=int(sys.argv[sys.argv.index("--port") + 1]), log_level="warning"
    )
