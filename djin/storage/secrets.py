"""Encrypted at-rest storage for OAuth tokens."""

from __future__ import annotations

import json
import os
import stat
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from djin.config import get_settings
from djin.storage.db import connect, utcnow


class VaultError(RuntimeError):
    pass


def _fernet() -> Fernet:
    settings = get_settings()
    if settings.encryption_key:
        key = settings.encryption_key.encode()
    else:
        key_file = settings.data_dir / "secret.key"
        if key_file.exists():
            key = key_file.read_bytes().strip()
        else:
            settings.ensure_dirs()
            key = Fernet.generate_key()
            key_file.write_bytes(key)
            os.chmod(key_file, stat.S_IRUSR | stat.S_IWUSR)
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise VaultError(
            "Invalid encryption key. Clear DJIN_ENCRYPTION_KEY or data/secret.key."
        ) from exc


def save_token(service: str, payload: dict[str, Any]) -> None:
    ciphertext = _fernet().encrypt(json.dumps(payload).encode())
    with connect() as conn:
        conn.execute(
            "INSERT INTO oauth_tokens (service, ciphertext, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(service) DO UPDATE SET ciphertext = excluded.ciphertext,"
            " updated_at = excluded.updated_at",
            (service, ciphertext, utcnow()),
        )


def load_token(service: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT ciphertext FROM oauth_tokens WHERE service = ?", (service,)
        ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(_fernet().decrypt(row["ciphertext"]).decode())
    except InvalidToken as exc:
        raise VaultError(
            f"Stored '{service}' token cannot be decrypted with the current key."
            " Re-run the login command for that service."
        ) from exc


def delete_token(service: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM oauth_tokens WHERE service = ?", (service,))


def has_token(service: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM oauth_tokens WHERE service = ?", (service,)
        ).fetchone()
    return row is not None
