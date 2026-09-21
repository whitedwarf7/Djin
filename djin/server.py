"""Local HTTP API and UI host for Djin. Binds to localhost only."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr

from djin import agent, auth, scheduler, voice
from djin.config import get_settings
from djin.integrations import google_auth
from djin.storage import db
from djin.tools import REGISTRY

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_TTS_CHARS = voice.MAX_TTS_CHARS


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="Djin", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
api = APIRouter(prefix="/api", dependencies=[Depends(auth.require_user)])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr


class RegistrationRequest(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )
    password: SecretStr


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


def _public_user(user: auth.AuthenticatedUser) -> dict[str, str]:
    return {"id": user.id, "username": user.username, "role": user.role}


def _issue_token(response: Response, user: auth.AuthenticatedUser) -> dict[str, Any]:
    settings = get_settings()
    token = auth.create_access_token(user)
    expires_in = settings.jwt_expire_minutes * 60
    response.set_cookie(
        key=auth.ACCESS_COOKIE,
        value=token,
        max_age=expires_in,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/api",
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": _public_user(user),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/auth/setup")
def auth_setup(request: Request, response: Response) -> dict[str, bool]:
    response.headers["Cache-Control"] = "no-store"
    return {
        "registration_required": db.count_users() == 0,
        "registration_allowed": auth.local_registration_allowed(request),
    }


@app.post("/api/auth/register", status_code=201)
def register(
    request: RegistrationRequest,
    http_request: Request,
    response: Response,
) -> dict[str, Any]:
    auth.require_local_registration(http_request)
    if db.count_users() != 0:
        raise HTTPException(status_code=409, detail="The owner account already exists.")

    try:
        username = auth.normalize_username(request.username)
        password = request.password.get_secret_value()
        auth.validate_new_password(password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    password_hash = auth.hash_password(password)
    try:
        row = db.create_first_user(username, password_hash)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    user = auth.AuthenticatedUser(
        id=str(row["id"]), username=str(row["username"]), role=str(row["role"])
    )
    return _issue_token(response, user)


@app.post("/api/auth/login")
def login(request: LoginRequest, http_request: Request, response: Response) -> dict[str, Any]:
    source = http_request.client.host if http_request.client else "unknown"
    auth.register_login_attempt(source)
    password = request.password.get_secret_value()
    user = auth.authenticate(request.username.strip(), password) if len(password) <= 128 else None
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    auth.clear_login_attempts(source)
    return _issue_token(response, user)


@app.post("/api/auth/logout", status_code=204)
def logout(
    response: Response,
    _user: auth.AuthenticatedUser = Depends(auth.require_user),
) -> None:
    response.delete_cookie(
        key=auth.ACCESS_COOKIE,
        httponly=True,
        secure=get_settings().auth_cookie_secure,
        samesite="strict",
        path="/api",
    )
    response.headers["Cache-Control"] = "no-store"


@app.get("/api/auth/me")
def current_user(user: auth.AuthenticatedUser = Depends(auth.require_user)) -> dict[str, str]:
    return _public_user(user)


@api.get("/status")
def status() -> dict[str, Any]:
    settings = get_settings()
    schedules = db.list_schedules()
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
            "search": {
                "configured": settings.search_configured,
                "provider": settings.search_provider,
            },
            "notes": {"configured": True, "path": str(settings.notes_dir)},
            "scheduler": {
                "configured": settings.scheduler_enabled,
                "connected": scheduler.is_running(),
                "count": len(schedules),
                "enabled_count": sum(item["enabled"] for item in schedules),
            },
            "notifications": {
                "configured": settings.ntfy_configured,
                "provider": "ntfy",
            },
        },
        "voice": voice.client_config(settings),
        "tools": [
            {"name": spec.name, "risk": spec.risk.value, "description": spec.description}
            for spec in REGISTRY.values()
        ],
    }


@api.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    try:
        return agent.start_turn(request.conversation_id, request.message).as_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@api.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    try:
        events = agent.stream_turn(request.conversation_id, request.message, request.voice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(_sse(events), media_type="text/event-stream", headers=SSE_HEADERS)


@api.post("/actions/{action_id}/decision")
def decide(action_id: str, request: DecisionRequest) -> dict[str, Any]:
    try:
        return agent.resolve_action(action_id, request.approve).as_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@api.post("/actions/{action_id}/decision/stream")
def decide_stream(action_id: str, request: DecisionRequest) -> StreamingResponse:
    try:
        events = agent.stream_resolution(action_id, request.approve, request.voice)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StreamingResponse(_sse(events), media_type="text/event-stream", headers=SSE_HEADERS)


@api.get("/voice/config")
def voice_config() -> dict[str, Any]:
    return voice.client_config()


@api.post("/voice/transcribe")
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


@api.post("/voice/speak")
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


@api.get("/conversations")
def conversations(limit: int = 30) -> list[dict[str, Any]]:
    return db.list_conversations(limit=min(limit, 100))


@api.get("/conversations/{conversation_id}")
def conversation(conversation_id: str) -> dict[str, Any]:
    metadata = db.get_conversation(conversation_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "conversation_id": conversation_id,
        "title": metadata["title"],
        "messages": db.get_messages(conversation_id),
        "pending": db.list_pending_actions(conversation_id),
    }


@api.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, bool]:
    if not db.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True}


@api.get("/audit", dependencies=[Depends(auth.require_admin)])
def audit(limit: int = 100) -> list[dict[str, Any]]:
    return db.read_audit(limit=min(limit, 500))


app.include_router(api)


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
