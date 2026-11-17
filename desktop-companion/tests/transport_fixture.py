"""Loopback-only protocol fixture. Uses no real user, model, MCP or Octop data."""

import asyncio
import json
import socket
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Header, Request, UploadFile, WebSocket
from fastapi.responses import StreamingResponse

app = FastAPI()


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
