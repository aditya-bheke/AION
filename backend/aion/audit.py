"""Append-only audit trail helper."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from aion.models import AuditEvent

# Actor naming convention:
#   "system:<component>"  - deterministic AION code (detector, validator, deployer)
#   "ai:<provider/model>" - output produced by a language model
#   "human:<name>"        - a person acting through the dashboard/API


def record(
    session: Session,
    action: str,
    actor: str,
    incident_id: Optional[int] = None,
    **details: Any,
) -> AuditEvent:
    event = AuditEvent(incident_id=incident_id, actor=actor, action=action, details=details)
    session.add(event)
    session.flush()
    return event
