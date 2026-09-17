"""Local HTTP API and UI host for Djin. Binds to localhost only."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from djin import agent
from djin.config import get_settings
from djin.integrations import google_auth, reddit_auth
from djin.storage import db
from djin.tools import REGISTRY

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Djin", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    conversation_id: str | None = None


class DecisionRequest(BaseModel):
    approve: bool


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


@app.post("/api/actions/{action_id}/decision")
def decide(action_id: str, request: DecisionRequest) -> dict[str, Any]:
    try:
        return agent.resolve_action(action_id, request.approve).as_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
