from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from djin.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    payload         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS pending_actions (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    tool_call_id    TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    risk            TEXT NOT NULL,
    arguments       TEXT NOT NULL,
    preview         TEXT NOT NULL,
    status          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    resolved_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_pending_conversation ON pending_actions(conversation_id, status);

CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT,
    tool_name       TEXT NOT NULL,
    risk            TEXT NOT NULL,
    arguments       TEXT NOT NULL,
    approval        TEXT NOT NULL,
    status          TEXT NOT NULL,
    detail          TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    service     TEXT PRIMARY KEY,
    ciphertext  BLOB NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    settings = get_settings()
    conn = sqlite3.connect(settings.db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    get_settings().ensure_dirs()
    with connect() as conn:
        conn.executescript(SCHEMA)


def create_conversation(title: str = "New conversation") -> str:
    conversation_id = uuid.uuid4().hex
    now = utcnow()
    with connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conversation_id, title, now, now),
        )
    return conversation_id


def conversation_exists(conversation_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    return row is not None


def append_message(conversation_id: str, payload: dict[str, Any]) -> None:
    now = utcnow()
    with connect() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, payload, created_at) VALUES (?, ?, ?)",
            (conversation_id, json.dumps(payload), now),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
        )


def get_messages(conversation_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT payload FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
    return [json.loads(row["payload"]) for row in rows]


def list_conversations(limit: int = 30) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT c.id, c.title, c.created_at, c.updated_at,"
            " (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id)"
            " AS message_count"
            " FROM conversations c ORDER BY c.updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_conversation(conversation_id: str) -> bool:
    """Drops the transcript and any unresolved approvals. The audit log is deliberately
    left intact - it is the record of what actually ran."""
    with connect() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute(
            "DELETE FROM pending_actions WHERE conversation_id = ?", (conversation_id,)
        )
        cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cursor.rowcount > 0


def set_conversation_title(conversation_id: str, title: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)
        )


def create_pending_action(
    *,
    conversation_id: str,
    tool_call_id: str,
    tool_name: str,
    risk: str,
    arguments: dict[str, Any],
    preview: str,
) -> dict[str, Any]:
    action_id = uuid.uuid4().hex
    now = utcnow()
    with connect() as conn:
        conn.execute(
            "INSERT INTO pending_actions"
            " (id, conversation_id, tool_call_id, tool_name, risk, arguments, preview,"
            "  status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (
                action_id,
                conversation_id,
                tool_call_id,
                tool_name,
                risk,
                json.dumps(arguments),
                preview,
                now,
            ),
        )
    return {
        "id": action_id,
        "conversation_id": conversation_id,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "risk": risk,
        "arguments": arguments,
        "preview": preview,
        "status": "pending",
        "created_at": now,
    }


def _row_to_action(row: sqlite3.Row) -> dict[str, Any]:
    action = dict(row)
    action["arguments"] = json.loads(action["arguments"])
    return action


def get_pending_action(action_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM pending_actions WHERE id = ?", (action_id,)
        ).fetchone()
    return _row_to_action(row) if row else None


def list_pending_actions(conversation_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_actions WHERE conversation_id = ? AND status = 'pending'"
            " ORDER BY created_at",
            (conversation_id,),
        ).fetchall()
    return [_row_to_action(row) for row in rows]


def resolve_pending_action(action_id: str, status: str) -> bool:
    """Mark a pending action approved/rejected. Returns False if already resolved."""
    with connect() as conn:
        cursor = conn.execute(
            "UPDATE pending_actions SET status = ?, resolved_at = ?"
            " WHERE id = ? AND status = 'pending'",
            (status, utcnow(), action_id),
        )
        return cursor.rowcount == 1


def log_audit(
    *,
    conversation_id: str | None,
    tool_name: str,
    risk: str,
    arguments: dict[str, Any],
    approval: str,
    status: str,
    detail: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO audit_log"
            " (conversation_id, tool_name, risk, arguments, approval, status, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                tool_name,
                risk,
                json.dumps(arguments)[:4000],
                approval,
                status,
                (detail or "")[:2000],
                utcnow(),
            ),
        )


def read_audit(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]
