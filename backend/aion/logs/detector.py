"""Incident detection: per-signature error-rate spike detection.

For every error signature seen in an ingested batch we compare:

    current  = occurrences in the last `window` seconds
    baseline = average occurrences per window over the preceding
               `baseline` seconds

and open an incident when

    current >= min_count  AND  current >= spike_ratio * baseline_avg

A brand-new error (baseline 0) therefore fires as soon as it reaches
`min_count`, while a long-standing low-rate error (noise) does not fire just
because it keeps happening. Events older than the closure of the previous
incident with the same signature are ignored, so late-arriving lines from
before a fix cannot re-open the problem; a genuine recurrence (regression)
after closure does open a new incident. Time is *event time* (log timestamps), not wall
clock, so replaying old logs behaves the same as live traffic.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aion import audit
from aion.config import settings
from aion.lifecycle import OPEN_STATES, Status
from aion.models import Incident, LogEvent, LogSignature, Service


def _count(session: Session, service_id: int, signature: str, start: datetime, end: datetime) -> int:
    return session.scalar(
        select(func.count(LogEvent.id)).where(
            LogEvent.service_id == service_id,
            LogEvent.signature == signature,
            LogEvent.timestamp > start,
            LogEvent.timestamp <= end,
        )
    ) or 0


def _title(sig: LogSignature, sample: LogEvent | None) -> str:
    if sample is not None and sample.exception_type:
        msg = (sample.exception_message or "").strip()
        return f"{sample.exception_type}: {msg}"[:200]
    return sig.template[:200]


def detect(session: Session, service: Service, signatures: set[str], now: datetime) -> list[int]:
    window = timedelta(seconds=settings.detection_window_seconds)
    baseline_span = timedelta(seconds=settings.detection_baseline_seconds)
    windows_in_baseline = max(baseline_span / window, 1.0)
    created: list[int] = []

    for signature in sorted(signatures):
        open_incident = session.scalar(
            select(Incident).where(
                Incident.service_id == service.id,
                Incident.signature == signature,
                Incident.status.in_(OPEN_STATES),
            )
        )
        if open_incident is not None:
            # Deduplication at incident level: attach, don't open a second incident.
            open_incident.last_seen = max(open_incident.last_seen, now)
            open_incident.event_count = _count(
                session, service.id, signature, open_incident.first_seen - timedelta(microseconds=1), now
            )
            continue

        # Errors logged before the last incident with this signature was closed
        # (e.g. lines still in flight while the fix was being deployed) belong to
        # that incident, not to a new one. Only a recurrence *after* closure counts.
        closed_at = session.scalar(
            select(func.max(Incident.updated_at)).where(
                Incident.service_id == service.id,
                Incident.signature == signature,
                Incident.status.not_in(OPEN_STATES),
            )
        )
        window_start = max(now - window, closed_at) if closed_at else now - window
        current = _count(session, service.id, signature, window_start, now)
        if current < settings.detection_min_count:
            continue
        baseline_total = _count(session, service.id, signature, now - window - baseline_span, now - window)
        baseline_avg = baseline_total / windows_in_baseline
        if current < settings.detection_spike_ratio * baseline_avg:
            continue

        sig = session.scalar(
            select(LogSignature).where(LogSignature.service_id == service.id, LogSignature.signature == signature)
        )
        first_in_window = session.scalar(
            select(func.min(LogEvent.timestamp)).where(
                LogEvent.service_id == service.id,
                LogEvent.signature == signature,
                LogEvent.timestamp > window_start,
            )
        )
        sample = session.scalar(
            select(LogEvent).where(LogEvent.service_id == service.id, LogEvent.signature == signature)
            .order_by(LogEvent.stack_trace.is_(None), LogEvent.id.desc()).limit(1)
        )
        reason = (
            f"{current} occurrences in the last {settings.detection_window_seconds}s "
            f"(threshold {settings.detection_min_count}); baseline average "
            f"{baseline_avg:.2f} per window over the previous {settings.detection_baseline_seconds}s "
            f"(spike ratio {settings.detection_spike_ratio}x)."
        )
        incident = Incident(
            service_id=service.id,
            title=_title(sig, sample),
            status=Status.DETECTED.value,
            severity="high" if baseline_total == 0 else "medium",
            signature=signature,
            detection_reason=reason,
            first_seen=first_in_window or now,
            last_seen=now,
            event_count=current,
        )
        session.add(incident)
        session.flush()
        audit.record(
            session,
            "incident_detected",
            "system:detector",
            incident_id=incident.id,
            service=service.name,
            signature=signature,
            reason=reason,
            new_error=baseline_total == 0,
        )
        created.append(incident.id)
    return created
