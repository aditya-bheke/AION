"""Incident endpoints, including the human-in-the-loop decisions."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aion import audit
from aion.api import serializers as ser
from aion.db import get_session
from aion.gitops.repo import GitRepo
from aion.lifecycle import RERUNNABLE_STATES, InvalidTransition, Status, transition
from aion.models import (utcnow, AITask, Approval, AuditEvent, CommitSuspect, Deployment, Incident, LogEvent, LogSignature,
                         PatchProposal, RCAReport, Service, ValidationRun)
from aion.pipeline.worker import enqueue_deploy, enqueue_pipeline, enqueue_rollback, worker
from aion.remediation.service import worktree_path
from aion.config import settings
from aion.integrations.github_flow import ci_gate, latest_pr, refresh_pull_request
from aion.schemas import DecisionIn
from aion.security import Principal, require_role

# Every incident endpoint requires a signed-in user; decisions need stronger roles.
router = APIRouter(prefix="/api/incidents", tags=["incidents"], dependencies=[Depends(require_role("viewer"))])


def _incident_or_404(session: Session, incident_id: int) -> Incident:
    inc = session.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(404, "Incident not found")
    return inc


def _latest_passed_patch(session: Session, incident_id: int) -> PatchProposal | None:
    return session.scalar(select(PatchProposal).where(PatchProposal.incident_id == incident_id,
                                                      PatchProposal.status.in_(["passed", "deployed"]))
                          .order_by(PatchProposal.id.desc()))


@router.get("")
def list_incidents(status: str | None = None, limit: int = 100, session: Session = Depends(get_session)):
    q = select(Incident, Service.name).join(Service).order_by(Incident.id.desc()).limit(min(limit, 500))
    if status:
        q = q.where(Incident.status == status)
    return [ser.incident(i, name) for i, name in session.execute(q)]


@router.get("/{incident_id}")
def get_incident(incident_id: int, session: Session = Depends(get_session)):
    inc = _incident_or_404(session, incident_id)
    svc = session.get(Service, inc.service_id)
    pr = latest_pr(session, inc.id)
    # Refresh from GitHub while CI is running, and after deployment until GitHub reports the PR
    # merged (GitHub detects the fast-forward asynchronously).
    if pr and pr.state == "open" and (pr.ci_state in ("none", "pending") or inc.status in ("resolved", "rolled_back")) and (
            pr.ci_checked_at is None or (utcnow() - pr.ci_checked_at).total_seconds() > settings.github_poll_seconds):
        session.commit()
        refresh_pull_request(pr.id)   # GitHub Actions status, fetched lazily while someone is looking
        session.expire_all()
        pr = latest_pr(session, inc.id)
    rca = session.scalar(select(RCAReport).where(RCAReport.incident_id == inc.id).order_by(RCAReport.id.desc()))
    patches = session.scalars(select(PatchProposal).where(PatchProposal.incident_id == inc.id)
                              .order_by(PatchProposal.id)).all()
    validations = session.scalars(select(ValidationRun).where(ValidationRun.incident_id == inc.id)
                                  .order_by(ValidationRun.id)).all()
    suspects = session.scalars(select(CommitSuspect).where(CommitSuspect.incident_id == inc.id)
                               .order_by(CommitSuspect.score.desc())).all()
    approvals = session.scalars(select(Approval).where(Approval.incident_id == inc.id).order_by(Approval.id)).all()
    deployments = session.scalars(select(Deployment).where(Deployment.incident_id == inc.id)).all()
    audit_rows = session.scalars(select(AuditEvent).where(AuditEvent.incident_id == inc.id)
                                 .order_by(AuditEvent.id)).all()
    return {
        "incident": ser.incident(inc, svc.name),
        "service": ser.service(svc),
        "suspects": [ser.suspect(s) for s in suspects],
        "rca": ser.rca(rca) if rca else None,
        "patches": [ser.patch(p) for p in patches],
        "validations": [ser.validation(v) for v in validations],
        "approvals": [ser.approval(a) for a in approvals],
        "deployments": [ser.deployment(d) for d in deployments],
        "audit": [ser.audit_event(a) for a in audit_rows],
        "pull_request": None if pr is None else {
            "number": pr.number, "url": pr.url, "repo": pr.repo, "branch": pr.branch, "head_sha": pr.head_sha,
            "state": pr.state, "ci_state": pr.ci_state, "ci_runs": pr.ci_runs, "patch_id": pr.patch_id,
            "required": settings.require_github_ci},
        "ai_tasks": [{"task_id": t.id, "purpose": t.purpose, "status": t.status, "agent": t.agent,
                      "created_at": ser._ts(t.created_at)}
                     for t in session.scalars(select(AITask).where(AITask.incident_id == inc.id).order_by(AITask.id))],
        "job_running": any(k in worker.busy_keys() for k in (f"incident-{inc.id}", f"deploy-{inc.id}",
                                                                  f"rollback-{inc.id}")),
    }


@router.get("/{incident_id}/logs")
def incident_logs(incident_id: int, limit: int = 20, session: Session = Depends(get_session)):
    """Raw events of the incident signature plus the deduplicated cluster view around it."""
    inc = _incident_or_404(session, incident_id)
    events = session.scalars(select(LogEvent).where(LogEvent.service_id == inc.service_id,
                                                    LogEvent.signature == inc.signature)
                             .order_by(LogEvent.id.desc()).limit(min(limit, 200))).all()
    start = inc.first_seen - timedelta(minutes=15)
    rows = session.execute(
        select(LogEvent.signature, LogEvent.level, func.count(LogEvent.id), func.min(LogEvent.timestamp),
               func.max(LogEvent.timestamp))
        .where(LogEvent.service_id == inc.service_id, LogEvent.timestamp >= start, LogEvent.timestamp <= inc.last_seen)
        .group_by(LogEvent.signature, LogEvent.level).order_by(func.count(LogEvent.id).desc())
    ).all()
    clusters = []
    for sig, level, count, first, last in rows:
        meta = session.scalar(select(LogSignature).where(LogSignature.service_id == inc.service_id,
                                                         LogSignature.signature == sig))
        clusters.append({"signature": sig, "level": level, "count": count, "template": meta.template if meta else "",
                         "first_seen": ser._ts(first), "last_seen": ser._ts(last),
                         "first_ever_seen": ser._ts(meta.first_seen) if meta else None,
                         "is_incident": sig == inc.signature})
    return {"events": [ser.log_event(e) for e in events], "clusters": clusters,
            "raw_events_in_window": sum(c["count"] for c in clusters)}


def approvals_for(session: Session, patch: PatchProposal) -> list[Approval]:
    """Approvals recorded for exactly this patch commit."""
    return session.scalars(select(Approval).where(Approval.patch_id == patch.id, Approval.decision == "approved",
                                                  Approval.commit_sha == patch.commit_sha)).all()


@router.post("/{incident_id}/rerun")
def rerun(incident_id: int, session: Session = Depends(get_session),
          user: Principal = Depends(require_role("engineer"))):
    inc = _incident_or_404(session, incident_id)
    if inc.status != Status.DETECTED.value and Status(inc.status) not in RERUNNABLE_STATES:
        raise HTTPException(409, f"Cannot re-run the pipeline from state {inc.status!r}")
    audit.record(session, "pipeline_rerun_requested", user.actor, incident_id=inc.id)
    session.commit()
    enqueue_pipeline(inc.id)
    return {"queued": True}


@router.post("/{incident_id}/approve")
def approve(incident_id: int, body: DecisionIn, session: Session = Depends(get_session),
            user: Principal = Depends(require_role("approver"))):
    inc = _incident_or_404(session, incident_id)
    if inc.status != Status.AWAITING_APPROVAL.value:
        raise HTTPException(409, f"Only incidents awaiting approval can be approved (current: {inc.status})")
    patch = _latest_passed_patch(session, inc.id)
    if patch is None or not patch.commit_sha:
        raise HTTPException(409, "No validated patch to approve")
    blocked = ci_gate(session, inc.id, patch)
    if blocked:
        raise HTTPException(409, blocked)
    existing = approvals_for(session, patch)
    if any(a.approver == user.name for a in existing):
        raise HTTPException(409, "You have already approved this patch; a different approver is required")
    # The approval is bound to the exact commit SHA that was validated, and to the signed-in user.
    session.add(Approval(incident_id=inc.id, patch_id=patch.id, commit_sha=patch.commit_sha, decision="approved",
                         approver=user.name, comment=body.comment))
    session.flush()
    count = len(existing) + 1
    if count < settings.required_approvals:
        audit.record(session, "approval_recorded", user.actor, incident_id=inc.id, patch_id=patch.id,
                     commit=patch.commit_sha, comment=body.comment,
                     progress=f"{count} of {settings.required_approvals} approvals")
        return {"status": inc.status, "approvals": count, "required": settings.required_approvals}
    transition(session, inc, Status.APPROVED, user.actor, patch_id=patch.id, commit=patch.commit_sha,
               comment=body.comment, approvals=count)
    return {"status": inc.status, "approvals": count, "required": settings.required_approvals}


@router.post("/{incident_id}/deploy")
def deploy(incident_id: int, session: Session = Depends(get_session),
           user: Principal = Depends(require_role("approver"))):
    inc = _incident_or_404(session, incident_id)
    if inc.status != Status.APPROVED.value:
        raise HTTPException(409, f"Deployment requires an approved incident (current: {inc.status})")
    transition(session, inc, Status.DEPLOYING, user.actor)
    session.commit()
    enqueue_deploy(inc.id, user.actor)
    return {"status": inc.status}


@router.post("/{incident_id}/rollback")
def rollback(incident_id: int, body: DecisionIn, session: Session = Depends(get_session),
             user: Principal = Depends(require_role("approver"))):
    """Revert a deployed AION fix (a production change, so it needs an approver)."""
    inc = _incident_or_404(session, incident_id)
    if inc.status not in (Status.RESOLVED.value, Status.DEPLOY_FAILED.value):
        raise HTTPException(409, f"Only resolved or failed deployments can be rolled back (current: {inc.status})")
    transition(session, inc, Status.ROLLING_BACK, user.actor, comment=body.comment)
    session.commit()
    enqueue_rollback(inc.id, user.actor)
    return {"status": inc.status}


@router.post("/{incident_id}/reject")
def reject(incident_id: int, body: DecisionIn, session: Session = Depends(get_session),
           user: Principal = Depends(require_role("approver"))):
    inc = _incident_or_404(session, incident_id)
    patch = session.scalar(select(PatchProposal).where(PatchProposal.incident_id == inc.id)
                           .order_by(PatchProposal.id.desc()))
    try:
        transition(session, inc, Status.REJECTED, user.actor, comment=body.comment)
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    if patch and patch.commit_sha:
        session.add(Approval(incident_id=inc.id, patch_id=patch.id, commit_sha=patch.commit_sha, decision="rejected",
                             approver=user.name, comment=body.comment))
    # Clean up the isolated worktrees of this incident (branches are kept for the record).
    svc = session.get(Service, inc.service_id)
    for p in session.scalars(select(PatchProposal).where(PatchProposal.incident_id == inc.id)):
        GitRepo(svc.repo_path).remove_worktree(worktree_path(svc, inc.id, p.attempt))
    return {"status": inc.status}
