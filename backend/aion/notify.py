"""Notifications (Slack, Discord, generic webhooks) - the outbox pattern on the audit trail.

The pipeline never sends notifications itself. Every important moment is already written to
the append-only audit trail inside the same transaction as the state change, so the audit
table *is* the outbox: a background notifier reads audit events newer than its stored cursor,
turns the interesting ones into messages and POSTs them to the configured channels.

Why: a slow or broken webhook can never delay or fail an incident's workflow; nothing is
lost if AION restarts (the cursor is in the database); and every attempt is logged.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

import httpx
from sqlalchemy import select

from aion.config import settings
from aion.db import session_scope
from aion.models import (AuditEvent, Incident, NotificationChannel, NotificationDelivery, NotifierCursor,
                         Service)
from aion.secrets_store import decrypt

log = logging.getLogger("aion.notify")

# Notification event -> human text. Keys are what admins subscribe to.
EVENTS = {
    "incident_detected": "🚨 New incident",
    "awaiting_approval": "🔒 Fix ready — human approval needed",
    "validation_failed": "✕ No fix passed validation — needs an engineer",
    "resolved": "✅ Fix deployed and verified",
    "deploy_failed": "⚠️ Deployment failed",
    "rolled_back": "↩ Fix rolled back",
    "error": "✕ Pipeline error",
}

_transport: Optional[httpx.BaseTransport] = None  # tests inject a MockTransport


def set_transport(transport: Optional[httpx.BaseTransport]) -> None:
    global _transport
    _transport = transport


def event_of(a: AuditEvent) -> Optional[str]:
    """Map an audit event to a notification event (or None if it is not interesting)."""
    if a.action == "incident_detected":
        return "incident_detected"
    if a.action == "status_changed":
        to = (a.details or {}).get("to_status")
        return to if to in EVENTS and to != "incident_detected" else None
    return None


def render(event: str, incident: Incident, service_name: str) -> str:
    link = f"{settings.public_url.rstrip('/')}/#/incidents/{incident.id}"
    return f"{EVENTS[event]}: incident #{incident.id} ({service_name}) — {incident.title}\n{link}"


def payload(kind: str, text: str, event: str, incident: Incident) -> dict[str, Any]:
    if kind == "slack":
        return {"text": text}
    if kind == "discord":
        return {"content": text[:1900]}
    return {"event": event, "incident_id": incident.id, "title": incident.title, "status": incident.status,
            "text": text}


def send(kind: str, url: str, body: dict[str, Any]) -> None:
    with httpx.Client(timeout=10, transport=_transport) as c:
        r = c.post(url, json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"webhook returned {r.status_code}: {r.text[:200]}")


def deliver_pending(batch: int = 200) -> int:
    """Process audit events after the cursor; returns how many notifications were attempted."""
    with session_scope() as s:
        cursor = s.get(NotifierCursor, 1)
        if cursor is None:
            # First start: begin at the current end of the trail (no flood of historical events).
            last = s.scalar(select(AuditEvent.id).order_by(AuditEvent.id.desc()).limit(1)) or 0
            s.add(NotifierCursor(id=1, last_audit_id=last))
            return 0
        events = s.scalars(select(AuditEvent).where(AuditEvent.id > cursor.last_audit_id)
                           .order_by(AuditEvent.id).limit(batch)).all()
        channels = s.scalars(select(NotificationChannel).where(NotificationChannel.enabled.is_(True))).all()
        jobs = []
        for a in events:
            ev = event_of(a)
            if not ev or a.incident_id is None:
                continue
            inc = s.get(Incident, a.incident_id)
            svc = s.get(Service, inc.service_id)
            for ch in channels:
                if ev in (ch.events or []):
                    jobs.append((ch.id, ch.kind, ch.url_encrypted, a.id, ev, inc, svc.name))
        new_cursor = events[-1].id if events else cursor.last_audit_id
        # Snapshot what the messages need, then release the transaction before any network call.
        prepared = [(cid, kind, enc, aid, ev, inc.id, render(ev, inc, name), payload(kind, render(ev, inc, name), ev, inc))
                    for cid, kind, enc, aid, ev, inc, name in jobs]
        cursor.last_audit_id = new_cursor
    attempted = 0
    for cid, kind, enc, aid, ev, iid, _text, body in prepared:
        status, error = "sent", None
        try:
            send(kind, decrypt(enc), body)
        except Exception as exc:  # a broken channel must never stop the notifier
            status, error = "failed", str(exc)[:500]
        with session_scope() as s:
            s.add(NotificationDelivery(channel_id=cid, audit_event_id=aid, event=ev, incident_id=iid,
                                       status=status, error=error))
        attempted += 1
    return attempted


class NotifierThread(threading.Thread):
    def __init__(self, interval: float = 3.0):
        super().__init__(name="aion-notifier", daemon=True)
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                deliver_pending()
            except Exception:
                log.exception("notifier pass failed")
            self._stop_event.wait(self.interval)

    def stop(self) -> None:
        self._stop_event.set()
