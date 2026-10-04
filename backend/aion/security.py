"""Authentication and authorisation.

* Passwords: PBKDF2-HMAC-SHA256 with a random 16-byte salt and 600,000
  iterations (OWASP 2023 recommendation), stored as
  ``pbkdf2_sha256$<iterations>$<salt b64>$<hash b64>``. Standard library only.
* Sessions: a random 256-bit bearer token is returned once at login; only its
  SHA-256 hash is stored, so a leaked database does not leak usable tokens.
  Sessions expire (AION_SESSION_HOURS) and can be revoked (logout).
* Roles are ordered: viewer < engineer < approver < admin. An endpoint
  declares the minimum role it needs with ``Depends(require_role("approver"))``.
* Machine clients (log shippers, CI, the demo driver) authenticate with the
  shared AION_SERVICE_TOKEN instead of a user session.
* Brute-force protection: 5 failed logins for a username within 15 minutes
  lock that username for the rest of the window (HTTP 429).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable, Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from aion.config import settings
from aion.db import get_session
from aion.models import User, UserSession, utcnow

ROLES = ["viewer", "engineer", "approver", "admin"]
_RANK = {r: i for i, r in enumerate(ROLES)}

MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 15 * 60


# ---- passwords ---------------------------------------------------------------------
def hash_password(password: str, iterations: Optional[int] = None) -> str:
    iterations = iterations or settings.password_iterations
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(iterations, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_b64, hash_b64 = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt_b64), int(iterations))
        return hmac.compare_digest(digest, base64.b64decode(hash_b64))  # constant-time comparison
    except (ValueError, TypeError):
        return False


def validate_new_password(password: str) -> None:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters")


# ---- users ---------------------------------------------------------------------------
def create_user(session: Session, username: str, password: str, role: str, display_name: str = "") -> User:
    if role not in _RANK:
        raise ValueError(f"Unknown role {role!r}; choose one of {', '.join(ROLES)}")
    validate_new_password(password)
    if session.scalar(select(User).where(User.username == username)):
        raise ValueError(f"User {username!r} already exists")
    user = User(username=username, display_name=display_name or username, role=role,
                password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


# ---- login throttling ------------------------------------------------------------------
_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


def _recent_failures(username: str) -> list[float]:
    cutoff = time.monotonic() - LOCKOUT_SECONDS
    with _failures_lock:
        _failures[username] = [t for t in _failures.get(username, []) if t > cutoff]
        return _failures[username]


def _record_failure(username: str) -> None:
    with _failures_lock:
        _failures.setdefault(username, []).append(time.monotonic())


def reset_login_throttle() -> None:
    with _failures_lock:
        _failures.clear()


# ---- sessions ------------------------------------------------------------------------
_dummy: dict[int, str] = {}


def _dummy_hash() -> str:
    it = settings.password_iterations
    if it not in _dummy:
        _dummy[it] = hash_password(secrets.token_urlsafe(16), it)
    return _dummy[it]


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def login(session: Session, username: str, password: str) -> tuple[str, User]:
    if len(_recent_failures(username)) >= MAX_FAILED_LOGINS:
        raise HTTPException(429, "Too many failed login attempts; try again later")
    user = session.scalar(select(User).where(User.username == username))
    # Always run a full-cost hash so response time does not reveal whether the user exists.
    ok = verify_password(password, user.password_hash if user else _dummy_hash())
    if not user or not ok or not user.active:
        _record_failure(username)
        raise HTTPException(401, "Invalid username or password")
    token = secrets.token_urlsafe(32)
    session.add(UserSession(token_hash=_token_hash(token), user_id=user.id,
                            expires_at=utcnow() + timedelta(hours=settings.session_hours)))
    session.flush()
    return token, user


def logout(session: Session, token: str) -> None:
    row = session.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
    if row:
        row.revoked = True


# ---- FastAPI dependencies --------------------------------------------------------------
@dataclass
class Principal:
    """Who is making the request."""
    kind: str                 # "user" | "service"
    name: str
    role: str
    user_id: Optional[int] = None

    @property
    def actor(self) -> str:   # audit-trail actor string
        if self.kind == "user":
            return f"human:{self.name}"
        return "ai:mcp-agent" if self.kind == "agent" else "system:service-client"


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _user_from_token(session: Session, token: str) -> Optional[Principal]:
    row = session.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
    if not row or row.revoked or row.expires_at < utcnow():
        return None
    user = session.get(User, row.user_id)
    if not user or not user.active:
        return None
    return Principal("user", user.username, user.role, user.id)


def require_role(min_role: str) -> Callable[..., Principal]:
    def dependency(authorization: Optional[str] = Header(default=None),
                   session: Session = Depends(get_session)) -> Principal:
        token = _bearer(authorization)
        principal = _user_from_token(session, token) if token else None
        if principal is None:
            raise HTTPException(401, "Sign in required", headers={"WWW-Authenticate": "Bearer"})
        if _RANK[principal.role] < _RANK[min_role]:
            raise HTTPException(403, f"This action requires the '{min_role}' role (you are '{principal.role}')")
        return principal
    return dependency


def require_agent(authorization: Optional[str] = Header(default=None)) -> Principal:
    """AI agents connected through the MCP connector: AION_AGENT_TOKEN only.

    Deliberately separate from users and from the service token: an agent can read
    incidents and answer AI tasks, and nothing else - no approve, no deploy, no ingest.
    """
    token = _bearer(authorization)
    if token and settings.agent_token and hmac.compare_digest(token, settings.agent_token):
        return Principal("agent", "mcp-agent", "agent")
    raise HTTPException(401, "Agent token required", headers={"WWW-Authenticate": "Bearer"})


def require_service_or_admin(authorization: Optional[str] = Header(default=None),
                             session: Session = Depends(get_session)) -> Principal:
    """Machine endpoints: the service token, or a signed-in admin."""
    token = _bearer(authorization)
    if token and settings.service_token and hmac.compare_digest(token, settings.service_token):
        return Principal("service", "service-client", "service")
    principal = _user_from_token(session, token) if token else None
    if principal and principal.role == "admin":
        return principal
    raise HTTPException(401, "Service token or admin sign-in required", headers={"WWW-Authenticate": "Bearer"})
