"""Login / logout / current user."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from aion import audit, security
from aion.config import settings
from aion.db import get_session
from aion.models import User
from aion.schemas import LoginIn
from aion.security import Principal, require_role

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_dict(user: User) -> dict:
    return {"username": user.username, "display_name": user.display_name, "role": user.role}


@router.post("/login")
def login(body: LoginIn, session: Session = Depends(get_session)):
    try:
        token, user = security.login(session, body.username, body.password)
    except Exception:
        audit.record(session, "login_failed", f"human:{body.username}")
        session.commit()  # keep the audit row even though the request fails
        raise
    audit.record(session, "login", f"human:{user.username}")
    return {"token": token, "expires_in_hours": settings.session_hours, "user": _user_dict(user)}


@router.post("/logout")
def logout(authorization: Optional[str] = Header(default=None), session: Session = Depends(get_session),
           principal: Principal = Depends(require_role("viewer"))):
    security.logout(session, (authorization or "")[7:].strip())
    audit.record(session, "logout", principal.actor)
    return {"ok": True}


@router.get("/me")
def me(principal: Principal = Depends(require_role("viewer")), session: Session = Depends(get_session)):
    user = session.get(User, principal.user_id)
    return {**_user_dict(user), "required_approvals": settings.required_approvals}
