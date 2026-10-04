"""Ingestion: store normalised events, maintain signatures, run detection."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aion.logs.detector import detect
from aion.logs.normalize import NormalizedEvent, normalize_event
from aion.models import LogEvent, LogSignature, Service


class IngestResult:
    def __init__(self) -> None:
        self.accepted = 0
        self.rejected = 0
        self.errors: list[str] = []
        self.new_incident_ids: list[int] = []


def ingest_events(session: Session, service: Service, raw_events: list[dict[str, Any]]) -> IngestResult:
    result = IngestResult()
    normalized: list[NormalizedEvent] = []
    for i, raw in enumerate(raw_events):
        try:
            normalized.append(normalize_event(raw))
        except (ValueError, TypeError) as exc:  # malformed record: skip it, keep the batch
            result.rejected += 1
            if len(result.errors) < 10:
                result.errors.append(f"event[{i}]: {exc}")
    if not normalized:
        return result

    sig_cache: dict[str, LogSignature] = {}
    for ev in normalized:
        row = LogEvent(
            service_id=service.id,
            timestamp=ev.timestamp,
            level=ev.level,
            logger=ev.logger,
            message=ev.message,
            template=ev.template,
            signature=ev.signature,
            exception_type=ev.exception_type,
            exception_message=ev.exception_message,
            stack_trace=ev.stack_trace,
            frames=ev.frames,
            request=ev.request,
            attributes=ev.attributes,
        )
        session.add(row)
        session.flush()

        sig = sig_cache.get(ev.signature) or session.scalar(
            select(LogSignature).where(LogSignature.service_id == service.id, LogSignature.signature == ev.signature)
        )
        if sig is None:
            sig = LogSignature(
                service_id=service.id,
                signature=ev.signature,
                level=ev.level,
                template=ev.template,
                exception_type=ev.exception_type,
                first_seen=ev.timestamp,
                last_seen=ev.timestamp,
                count=0,
                sample_event_id=row.id,
            )
            session.add(sig)
        sig.count += 1
        sig.first_seen = min(sig.first_seen, ev.timestamp)
        sig.last_seen = max(sig.last_seen, ev.timestamp)
        if ev.stack_trace and sig.sample_event_id is None:
            sig.sample_event_id = row.id
        sig_cache[ev.signature] = sig
        result.accepted += 1

    session.flush()
    error_sigs = {ev.signature for ev in normalized if ev.is_error}
    if error_sigs:
        latest = max(ev.timestamp for ev in normalized)
        result.new_incident_ids = detect(session, service, error_sigs, latest)
    return result
