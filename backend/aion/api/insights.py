"""Incident-response metrics, computed from the incidents and their audit trail.

Per incident (all from recorded timestamps, nothing estimated):
  MTTD            first error log line -> incident opened            (detection)
  time to fix     incident opened -> first `awaiting_approval`       (AION's automated work)
  decision time   `awaiting_approval` -> `approved`                  (the human gate)
  deploy time     `approved` -> `resolved`                           (deploy + verification)
  MTTR            first error log line -> `resolved`                 (end to end)
"""
from __future__ import annotations

from statistics import mean, median
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aion.db import get_session
from aion.models import AuditEvent, Incident, PatchProposal, PullRequest, RCAReport, Service, ValidationRun
from aion.security import Principal, require_role

router = APIRouter(prefix="/api", tags=["insights"])


def _secs(a, b) -> Optional[float]:
    return round((b - a).total_seconds(), 1) if a and b else None


def _summary(values: list[float]) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"count": 0, "median": None, "mean": None}
    return {"count": len(vals), "median": round(median(vals), 1), "mean": round(mean(vals), 1)}


@router.get("/insights")
def insights(session: Session = Depends(get_session), _: Principal = Depends(require_role("viewer"))):
    incidents = session.execute(select(Incident, Service.name).join(Service).order_by(Incident.id)).all()
    # First time each incident entered each status.
    first: dict[int, dict[str, object]] = {}
    for a in session.scalars(select(AuditEvent).where(AuditEvent.action == "status_changed",
                                                      AuditEvent.incident_id.is_not(None)).order_by(AuditEvent.id)):
        first.setdefault(a.incident_id, {}).setdefault((a.details or {}).get("to_status"), a.timestamp)

    rows = []
    for inc, svc in incidents:
        t = first.get(inc.id, {})
        rows.append({
            "id": inc.id, "service": svc, "title": inc.title, "status": inc.status,
            "mttd_s": _secs(inc.first_seen, inc.created_at),
            "time_to_fix_s": _secs(inc.created_at, t.get("awaiting_approval")),
            "decision_s": _secs(t.get("awaiting_approval"), t.get("approved")),
            "deploy_s": _secs(t.get("approved"), t.get("resolved")),
            "mttr_s": _secs(inc.first_seen, t.get("resolved")),
            "rolled_back": "rolled_back" in t,
        })

    patches = session.execute(select(PatchProposal.strategy, PatchProposal.status, func.count())
                              .group_by(PatchProposal.strategy, PatchProposal.status)).all()
    by_strategy: dict[str, dict[str, int]] = {}
    for strategy, status, n in patches:
        by_strategy.setdefault(strategy, {})[status] = n
    runs = dict(session.execute(select(ValidationRun.status, func.count()).group_by(ValidationRun.status)).all())
    ci = dict(session.execute(select(PullRequest.ci_state, func.count()).group_by(PullRequest.ci_state)).all())
    analyzers = dict(session.execute(select(RCAReport.analyzer, func.count()).group_by(RCAReport.analyzer)).all())
    by_status = dict(session.execute(select(Incident.status, func.count()).group_by(Incident.status)).all())

    return {
        "timings": {k: _summary([r[k] for r in rows]) for k in ("mttd_s", "time_to_fix_s", "decision_s",
                                                                "deploy_s", "mttr_s")},
        "incidents_by_status": by_status,
        "patches_by_strategy": by_strategy,
        "validation_runs": runs,
        "github_ci": ci,
        "rca_analyzers": analyzers,
        "rollbacks": sum(1 for r in rows if r["rolled_back"]),
        "incidents": rows[-25:][::-1],
    }
