"""Loopback-only protocol fixture. Uses no real user, model, MCP or Octop data."""

import asyncio
import json
import socket
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Header, Request, UploadFile, WebSocket
from fastapi.responses import StreamingResponse

app = FastAPI()
team_record={"team_id":"team-created","agent_id":"team-created","name":"测试团队","primary_agent_id":"owned","primary_agent_name":"小通","member_ids":["owned","member"],"members":[],"kind":"team"}
@app.get("/api/companion/agents")
async def allowed_agents(authorization:str=Header()):
    assert authorization=="Bearer fixture-only-token"
    return [{"agent_id":id} for id in ["owned","member","team-created","other-host"]]
@app.get("/api/agents/{agent}")
async def primary(agent:str,authorization:str=Header()):
    assert authorization=="Bearer fixture-only-token"
    return {"agent_id":agent,"name":"小通","is_team_primary":agent=="owned"}
@app.get("/api/teams/team-created")
async def get_team(authorization:str=Header()):
    assert authorization=="Bearer fixture-only-token";return team_record
@app.post("/api/teams")
async def create_team(request:Request,authorization:str=Header()):
    assert authorization=="Bearer fixture-only-token"
    body=await request.json();assert set(body)=={"name","member_ids"} and body["member_ids"]==["member"]
    team_record.update(name=body["name"]);return team_record
@app.patch("/api/teams/team-created")
async def update_team(request:Request,authorization:str=Header()):
    return await create_team(request,authorization)


@app.websocket("/api/agents/owned/chat/ws")
async def chat(socket: WebSocket):
    assert socket.headers.get("authorization") == "Bearer fixture-only-token"
    await socket.accept()
    body = await socket.receive_json()
    assert body == {"type": "cancel", "thread_id": "thread-1"}
    await socket.send_json({"type": "cancel_received"})


@app.post("/api/agents/owned/chat/hitl/resume")
async def resume(request: Request, authorization: str = Header()):
    assert authorization == "Bearer fixture-only-token"
    body = await request.json()
    assert set(body) == {"thread_id", "pending_id", "decisions"}
    assert body["pending_id"] == "pending-1"
    assert body["decisions"] == [{"type": "respond", "message": "只看本周"}]

    async def events():
        for frame in [
            {"type": "turn.resumed", "turn_id": "turn-1"},
            {"type": "token", "content": "已确认中文回答"},
            {"type": "done"},
        ]:
            yield "event: chunk\ndata: " + json.dumps(frame, ensure_ascii=False) + "\n\n"
            await asyncio.sleep(0.03)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/api/agents/owned/upload")
async def upload(file: UploadFile, authorization: str = Header()):
    assert authorization == "Bearer fixture-only-token"
    assert await file.read() == b"fixture"
    return {
        "filename": file.filename,
        "path": "inbound/" + file.filename,
        "media_type": file.content_type,
    }


if __name__ == "__main__":
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    Path("desktop-companion/build/transport-fixture.port").write_text(
        str(listener.getsockname()[1])
    )
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[listener])
