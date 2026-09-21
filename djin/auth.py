"""Username/password authentication and JWT authorization."""

from __future__ import annotations

import os
import re
import secrets
import stat
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from math import ceil
from ipaddress import ip_address
from pathlib import Path
from threading import Lock

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash

from djin.config import get_settings
from djin.storage import db

ACCESS_COOKIE = "djin_access_token"
ALGORITHM = "HS256"
ISSUER = "djin"
AUDIENCE = "djin-web"
LOGIN_ATTEMPT_LIMIT = 5
LOGIN_WINDOW_SECONDS = 60
MAX_LOGIN_SOURCES = 2_048
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$")
PROXY_HEADERS = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto")

_bearer = HTTPBearer(auto_error=False)
_password_hash = PasswordHash.recommended()
_login_attempts: OrderedDict[str, deque[float]] = OrderedDict()
_login_lock = Lock()


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    username: str
    role: str


def normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Username must be 3-64 characters using letters, numbers, dots, hyphens, or underscores."
        )
    return normalized


def validate_new_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters.")
    if len(password) > 128:
        raise ValueError("Password must be at most 128 characters.")


def require_local_registration(request: Request) -> None:
    if not local_registration_allowed(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The first account can only be created from the local Djin page.",
        )


def local_registration_allowed(request: Request) -> bool:
    if any(request.headers.get(header) for header in PROXY_HEADERS):
        return False
    client_host = request.client.host if request.client else ""
    request_host = request.url.hostname or ""
    origin = request.headers.get("origin")

    local = _is_loopback(client_host) and _is_loopback(request_host)
    if origin:
        local = local and origin.rstrip("/") == str(request.base_url).rstrip("/")
    return local


def _is_loopback(host: str) -> bool:
    if host.rstrip(".").lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    return hash_password(secrets.token_urlsafe(32))


def authenticate(username: str, password: str) -> AuthenticatedUser | None:
    row = db.get_user_by_username(username)
    if row is None:
        _password_hash.verify(password, _dummy_password_hash())
        return None
    if not row["is_active"]:
        return None
    if not _password_hash.verify(password, row["password_hash"]):
        return None
    return _authenticated_user(row)


@lru_cache(maxsize=1)
def _signing_key() -> str:
    settings = get_settings()
    if settings.jwt_secret:
        return settings.jwt_secret
    return _load_or_create_secret(settings.data_dir / "auth.key")


def _load_or_create_secret(path: Path) -> str:
    generated = secrets.token_urlsafe(48)
    for _ in range(100):
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                stat.S_IRUSR | stat.S_IWUSR,
            )
        except FileExistsError:
            try:
                value = path.read_text(encoding="ascii").strip()
            except (OSError, UnicodeDecodeError):
                value = ""
            if len(value.encode()) >= 32:
                return value
            time.sleep(0.01)
            continue

        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(generated)
            handle.flush()
            os.fsync(handle.fileno())
        return generated
    raise RuntimeError(f"{path} is invalid or could not be initialized.")


def register_login_attempt(source: str) -> None:
    now = time.monotonic()
    with _login_lock:
        for known_source, known_attempts in list(_login_attempts.items()):
            while known_attempts and known_attempts[0] <= now - LOGIN_WINDOW_SECONDS:
                known_attempts.popleft()
            if not known_attempts:
                del _login_attempts[known_source]
        while len(_login_attempts) >= MAX_LOGIN_SOURCES and source not in _login_attempts:
            _login_attempts.popitem(last=False)

        attempts = _login_attempts.setdefault(source, deque())
        _login_attempts.move_to_end(source)
        if len(attempts) >= LOGIN_ATTEMPT_LIMIT:
            retry_after = max(1, ceil(attempts[0] + LOGIN_WINDOW_SECONDS - now))
        else:
            attempts.append(now)
            return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many sign-in attempts. Try again shortly.",
        headers={"Retry-After": str(retry_after)},
    )


def clear_login_attempts(source: str) -> None:
    with _login_lock:
        _login_attempts.pop(source, None)


def create_access_token(user: AuthenticatedUser) -> str:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=get_settings().jwt_expire_minutes)
    return jwt.encode(
        {
            "sub": user.id,
            "username": user.username,
            "role": user.role,
            "type": "access",
            "iat": now,
            "exp": expires,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "jti": secrets.token_hex(16),
        },
        _signing_key(),
        algorithm=ALGORITHM,
    )


def _decode_subject(token: str) -> str:
    try:
        payload = jwt.decode(
            token,
            _signing_key(),
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["sub", "type", "iat", "exp", "iss", "aud", "jti"]},
        )
    except jwt.InvalidTokenError as exc:
        raise _unauthorized("Invalid or expired access token.") from exc
    if payload.get("type") != "access" or not isinstance(payload.get("sub"), str):
        raise _unauthorized("Invalid access token.")
    return payload["sub"]


def _authenticated_user(row: dict[str, object]) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=str(row["id"]),
        username=str(row["username"]),
        role=str(row["role"]),
    )


def _unauthorized(detail: str = "Authentication required.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    cookie_token = request.cookies.get(ACCESS_COOKIE)
    token = credentials.credentials if credentials else cookie_token
    if not token:
        raise _unauthorized()
    if credentials is None and cookie_token and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        expected_origin = str(request.base_url).rstrip("/")
        if origin and origin.rstrip("/") != expected_origin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-origin request rejected.",
            )

    row = db.get_user_by_id(_decode_subject(token))
    if row is None or not row["is_active"]:
        raise _unauthorized("This account is no longer active.")
    return _authenticated_user(row)


def require_admin(user: AuthenticatedUser = Depends(require_user)) -> AuthenticatedUser:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required.",
        )
    return user