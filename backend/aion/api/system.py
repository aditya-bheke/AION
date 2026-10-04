"""System status and global audit log."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aion.ai.providers.factory import get_provider, resolve_provider_kind
from aion.api import serializers as ser
from aion.config import settings
from aion.db import get_session
from aion.models import AuditEvent, Incident, LogEvent, Service
from aion.pipeline.worker import worker

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/system")
def system_status(session: Session = Depends(get_session)):
    try:
        provider = get_provider(settings)
        provider_name, provider_error = (provider.name if provider else None), None
    except Exception as exc:
        provider_name, provider_error = None, str(exc)
    by_status = dict(session.execute(select(Incident.status, func.count(Incident.id)).group_by(Incident.status)).all())
    return {
        "llm": {"kind": resolve_provider_kind(settings), "provider": provider_name, "error": provider_error,
                "mode": "llm" if provider_name else "heuristic (no LLM configured)"},
        "detection": {"window_seconds": settings.detection_window_seconds,
                      "min_count": settings.detection_min_count,
                      "baseline_seconds": settings.detection_baseline_seconds,
                      "spike_ratio": settings.detection_spike_ratio},
        "pipeline": {"auto_pipeline": settings.auto_pipeline, "max_patch_attempts": settings.max_patch_attempts,
                     "running_jobs": worker.busy_keys()},
        "counts": {"services": session.scalar(select(func.count(Service.id))),
                   "log_events": session.scalar(select(func.count(LogEvent.id))),
                   "incidents": by_status},
    }


@router.get("/audit")
def audit_log(incident_id: int | None = None, limit: int = 200, session: Session = Depends(get_session)):
    q = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(min(limit, 1000))
    if incident_id is not None:
        q = q.where(AuditEvent.incident_id == incident_id)
    return [ser.audit_event(a) for a in session.scalars(q)]
