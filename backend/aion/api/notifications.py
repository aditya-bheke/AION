"""Notification channels (admin) and delivery log."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from aion import audit, notify
from aion.api import serializers as ser
from aion.db import get_session
from aion.models import NotificationChannel, NotificationDelivery
from aion.secrets_store import SecretsUnavailable, decrypt, encrypt
from aion.security import Principal, require_role

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern="^(slack|discord|webhook)$")
    url: Optional[str] = Field(default=None, max_length=1000, description="omit on update to keep the stored URL")
    events: list[str] = Field(default_factory=lambda: ["awaiting_approval", "validation_failed", "deploy_failed",
                                                       "resolved", "rolled_back"])
    enabled: bool = True


def _hint(url: str) -> str:
    """Show only scheme + host of a webhook URL (the path contains the secret)."""
    parts = url.split("/")
    return "/".join(parts[:3]) + "/…" if len(parts) > 3 else "…"


def _out(c: NotificationChannel) -> dict:
    return {"id": c.id, "name": c.name, "kind": c.kind, "url_hint": c.url_hint, "events": c.events,
            "enabled": c.enabled, "created_by": c.created_by, "created_at": ser._ts(c.created_at)}


def _validate(body: ChannelIn) -> None:
    unknown = set(body.events) - set(notify.EVENTS)
    if unknown:
        raise HTTPException(422, f"Unknown events: {sorted(unknown)}; choose from {sorted(notify.EVENTS)}")
    if body.url is not None and not body.url.startswith(("https://", "http://")):
        raise HTTPException(422, "Webhook URL must start with https:// (or http:// for local testing)")


@router.get("/events")
def events(_: Principal = Depends(require_role("viewer"))):
    return [{"id": k, "label": v} for k, v in notify.EVENTS.items()]


@router.get("/channels")
def list_channels(session: Session = Depends(get_session), _: Principal = Depends(require_role("viewer"))):
    return [_out(c) for c in session.scalars(select(NotificationChannel).order_by(NotificationChannel.id))]


@router.post("/channels")
def create_channel(body: ChannelIn, session: Session = Depends(get_session),
                   user: Principal = Depends(require_role("admin"))):
    _validate(body)
    if not body.url:
        raise HTTPException(422, "Webhook URL is required")
    try:
        enc = encrypt(body.url)
    except SecretsUnavailable as exc:
        raise HTTPException(409, str(exc))
    c = NotificationChannel(name=body.name, kind=body.kind, url_encrypted=enc, url_hint=_hint(body.url),
                            events=body.events, enabled=body.enabled, created_by=user.name)
    session.add(c)
    session.flush()
    audit.record(session, "notification_channel_created", user.actor, channel=c.name, kind=c.kind, events=c.events)
    return _out(c)


@router.put("/channels/{channel_id}")
def update_channel(channel_id: int, body: ChannelIn, session: Session = Depends(get_session),
                   user: Principal = Depends(require_role("admin"))):
    c = session.get(NotificationChannel, channel_id)
    if c is None:
        raise HTTPException(404, "Channel not found")
    _validate(body)
    c.name, c.kind, c.events, c.enabled = body.name, body.kind, body.events, body.enabled
    if body.url:
        c.url_encrypted, c.url_hint = encrypt(body.url), _hint(body.url)
    audit.record(session, "notification_channel_updated", user.actor, channel=c.name, enabled=c.enabled)
    return _out(c)


@router.delete("/channels/{channel_id}")
def delete_channel(channel_id: int, session: Session = Depends(get_session),
                   user: Principal = Depends(require_role("admin"))):
    c = session.get(NotificationChannel, channel_id)
    if c is None:
        raise HTTPException(404, "Channel not found")
    c.enabled = False   # keep the row: deliveries reference it and the audit trail stays meaningful
    c.events = []
    audit.record(session, "notification_channel_disabled", user.actor, channel=c.name)
    return {"ok": True}


@router.post("/channels/{channel_id}/test")
def test_channel(channel_id: int, session: Session = Depends(get_session),
                 user: Principal = Depends(require_role("admin"))):
    c = session.get(NotificationChannel, channel_id)
    if c is None:
        raise HTTPException(404, "Channel not found")
    text = f"✅ AION test notification from {user.name} — this channel is connected."
    body = {"text": text} if c.kind == "slack" else {"content": text} if c.kind == "discord" else \
        {"event": "test", "text": text}
    try:
        notify.send(c.kind, decrypt(c.url_encrypted), body)
    except Exception as exc:
        return {"ok": False, "message": str(exc)[:300]}
    return {"ok": True, "message": "Delivered."}


@router.get("/deliveries")
def deliveries(limit: int = 50, session: Session = Depends(get_session), _: Principal = Depends(require_role("viewer"))):
    rows = session.scalars(select(NotificationDelivery).order_by(NotificationDelivery.id.desc()).limit(min(limit, 500)))
    return [{"id": d.id, "channel_id": d.channel_id, "event": d.event, "incident_id": d.incident_id,
             "status": d.status, "error": d.error, "created_at": ser._ts(d.created_at)} for d in rows]
