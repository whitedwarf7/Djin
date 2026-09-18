"""Local HTTP API and UI host for Djin. Binds to localhost only."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from djin import agent, voice
from djin.config import get_settings
from djin.integrations import google_auth, reddit_auth
from djin.storage import db
from djin.tools import REGISTRY

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_TTS_CHARS = voice.MAX_TTS_CHARS


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Djin", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    conversation_id: str | None = None
    voice: bool = False


class DecisionRequest(BaseModel):
    approve: bool
    voice: bool = False


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TTS_CHARS)
    voice: str | None = Field(default=None, max_length=64)
    format: str = "mp3"


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(events: Iterator[dict[str, Any]]) -> Iterator[str]:
    for event in events:
        yield f"data: {json.dumps(event)}\n\n"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "llm_key_present": bool(settings.llm_api_key),
        "auto_approve_write": settings.auto_approve_write,
        "integrations": {
            "google": {
                "configured": settings.google_configured,
                "connected": google_auth.is_connected(),
            },
            "reddit": {
                "configured": settings.reddit_configured,
                "connected": reddit_auth.is_connected(),
            },
            "search": {
                "configured": settings.search_configured,
                "provider": settings.search_provider,
            },
            "notes": {"configured": True, "path": str(settings.notes_dir)},
        },
        "voice": voice.client_config(settings),
        "tools": [
            {"name": spec.name, "risk": spec.risk.value, "description": spec.description}
            for spec in REGISTRY.values()
        ],
    }


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    try:
        return agent.start_turn(request.conversation_id, request.message).as_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    try:
        events = agent.stream_turn(request.conversation_id, request.message, request.voice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(_sse(events), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/actions/{action_id}/decision")
def decide(action_id: str, request: DecisionRequest) -> dict[str, Any]:
    try:
        return agent.resolve_action(action_id, request.approve).as_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/actions/{action_id}/decision/stream")
def decide_stream(action_id: str, request: DecisionRequest) -> StreamingResponse:
    try:
        events = agent.stream_resolution(action_id, request.approve, request.voice)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StreamingResponse(_sse(events), media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/api/voice/config")
def voice_config() -> dict[str, Any]:
    return voice.client_config()


@app.post("/api/voice/transcribe")
async def voice_transcribe(
    audio: UploadFile = File(...),
    language: str | None = Form(default=None),
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.voice_enabled:
        raise HTTPException(status_code=403, detail="Voice is disabled.")

    payload = await audio.read(settings.max_audio_bytes + 1)
    if len(payload) > settings.max_audio_bytes:
        raise HTTPException(status_code=413, detail="Audio clip is too large.")
    try:
        return {"text": voice.transcribe(payload, audio.content_type or "", language, settings)}
    except voice.VoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/voice/speak")
def voice_speak(request: SpeakRequest) -> Response:
    settings = get_settings()
    if not settings.voice_enabled:
        raise HTTPException(status_code=403, detail="Voice is disabled.")
    try:
        audio, media_type = voice.synthesise(
            request.text, request.voice, request.format, settings
        )
    except voice.VoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=audio, media_type=media_type, headers={"Cache-Control": "no-store"})


@app.get("/api/conversations")
def conversations(limit: int = 30) -> list[dict[str, Any]]:
    return db.list_conversations(limit=min(limit, 100))


@app.get("/api/conversations/{conversation_id}")
def conversation(conversation_id: str) -> dict[str, Any]:
    if not db.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "conversation_id": conversation_id,
        "messages": db.get_messages(conversation_id),
        "pending": db.list_pending_actions(conversation_id),
    }


@app.get("/api/audit")
def audit(limit: int = 100) -> list[dict[str, Any]]:
    return db.read_audit(limit=min(limit, 500))


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
