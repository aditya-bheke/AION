"""Incident lifecycle: an explicit finite-state machine.

Every status change goes through `transition()`, which refuses any move that
is not listed in ALLOWED_TRANSITIONS. This is what makes the human-approval
guarantee structural: there is no edge from `awaiting_approval` to
`deploying`; the only way there is through `approved`, and only the
human-approval API performs that transition.
"""
from __future__ import annotations

from enum import Enum

from sqlalchemy.orm import Session

from aion import audit
from aion.models import Incident


class Status(str, Enum):
    DETECTED = "detected"
    ANALYZING = "analyzing"
    PATCHING = "patching"
    VALIDATING = "validating"
    AWAITING_APPROVAL = "awaiting_approval"
    VALIDATION_FAILED = "validation_failed"
    APPROVED = "approved"
    DEPLOYING = "deploying"
    RESOLVED = "resolved"
    DEPLOY_FAILED = "deploy_failed"
    REJECTED = "rejected"
    ERROR = "error"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"


S = Status

ALLOWED_TRANSITIONS: dict[Status, set[Status]] = {
    S.DETECTED: {S.ANALYZING, S.REJECTED},
    S.ANALYZING: {S.PATCHING, S.ERROR},
    S.PATCHING: {S.VALIDATING, S.VALIDATION_FAILED, S.ERROR},
    # A failed validation may loop back to PATCHING (generate-validate-repair).
    S.VALIDATING: {S.AWAITING_APPROVAL, S.PATCHING, S.VALIDATION_FAILED, S.ERROR},
    # Only a human (approval API) leaves AWAITING_APPROVAL.
    S.AWAITING_APPROVAL: {S.APPROVED, S.REJECTED},
    S.VALIDATION_FAILED: {S.ANALYZING, S.REJECTED},
    S.APPROVED: {S.DEPLOYING, S.REJECTED},  # a human may still withdraw before deploying
    S.DEPLOYING: {S.RESOLVED, S.DEPLOY_FAILED},
    # A failed post-deploy verification may be rolled back automatically.
    S.DEPLOY_FAILED: {S.ANALYZING, S.REJECTED, S.ROLLING_BACK},
    S.ERROR: {S.ANALYZING, S.REJECTED},
    # A deployed fix can be rolled back by an approver (revert commit, redeploy, verify).
    S.RESOLVED: {S.ROLLING_BACK},
    S.ROLLING_BACK: {S.ROLLED_BACK, S.ERROR},
    # After a rollback the original bug is back in production: investigate again or close.
    S.ROLLED_BACK: {S.ANALYZING, S.REJECTED},
    S.REJECTED: set(),
}

# States in which an incident is still "open" (new matching errors attach to it).
OPEN_STATES = {s.value for s in Status if s not in (S.RESOLVED, S.REJECTED)}
# States from which a human may restart the automated investigation.
RERUNNABLE_STATES = {S.VALIDATION_FAILED, S.DEPLOY_FAILED, S.ERROR, S.ROLLED_BACK}


class InvalidTransition(Exception):
    def __init__(self, current: str, target: str):
        super().__init__(f"Illegal incident transition {current!r} -> {target!r}")
        self.current = current
        self.target = target


def can_transition(current: str, target: Status) -> bool:
    return target in ALLOWED_TRANSITIONS[Status(current)]


def transition(session: Session, incident: Incident, target: Status, actor: str, **details) -> None:
    current = incident.status
    if not can_transition(current, target):
        raise InvalidTransition(current, target.value)
    incident.status = target.value
    audit.record(
        session,
        "status_changed",
        actor,
        incident_id=incident.id,
        from_status=current,
        to_status=target.value,
        **details,
    )
    session.flush()
