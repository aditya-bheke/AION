"""Convert ORM rows to JSON-friendly dicts for the API."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from aion.models import (Approval, AuditEvent, CommitSuspect, Deployment, Incident, LogEvent, PatchProposal,
                         RCAReport, Service, ValidationRun)


def _ts(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def service(s: Service) -> dict[str, Any]:
    return {"id": s.id, "name": s.name, "repo_path": s.repo_path, "production_branch": s.production_branch,
            "log_path": s.log_path, "test_command": s.test_command, "run_command": s.run_command,
            "health_path": s.health_path, "production_url": s.production_url, "created_at": _ts(s.created_at)}


def incident(i: Incident, service_name: str | None = None) -> dict[str, Any]:
    return {"id": i.id, "service_id": i.service_id, "service": service_name, "title": i.title, "status": i.status,
            "severity": i.severity, "signature": i.signature, "detection_reason": i.detection_reason,
            "first_seen": _ts(i.first_seen), "last_seen": _ts(i.last_seen), "event_count": i.event_count,
            "pipeline_error": i.pipeline_error, "created_at": _ts(i.created_at), "updated_at": _ts(i.updated_at)}


def log_event(e: LogEvent) -> dict[str, Any]:
    return {"id": e.id, "timestamp": _ts(e.timestamp), "level": e.level, "logger": e.logger, "message": e.message,
            "template": e.template, "signature": e.signature, "exception_type": e.exception_type,
            "exception_message": e.exception_message, "stack_trace": e.stack_trace, "frames": e.frames,
            "request": e.request}


def deployment(d: Deployment) -> dict[str, Any]:
    return {"id": d.id, "service_id": d.service_id, "environment": d.environment, "version": d.version,
            "commit_sha": d.commit_sha, "deployed_at": _ts(d.deployed_at), "deployed_by": d.deployed_by,
            "incident_id": d.incident_id, "status": d.status, "notes": d.notes}


def suspect(c: CommitSuspect) -> dict[str, Any]:
    return {"commit_sha": c.commit_sha, "author": c.author, "authored_at": _ts(c.authored_at), "message": c.message,
            "files_changed": c.files_changed, "score": c.score, "reasons": c.reasons,
            "deployment_version": c.deployment_version}


def rca(r: RCAReport) -> dict[str, Any]:
    return {"id": r.id, "analyzer": r.analyzer, "probable_root_cause": r.probable_root_cause,
            "observed_evidence": r.observed_evidence, "inferences": r.inferences,
            "affected_service": r.affected_service, "affected_files": r.affected_files,
            "suspected_commit": r.suspected_commit, "confidence": r.confidence, "remediation": r.remediation,
            "grounding_warnings": r.grounding_warnings, "evidence_pack": r.evidence_pack,
            "raw_response": r.raw_response, "usage": r.usage, "created_at": _ts(r.created_at)}


def patch(p: PatchProposal) -> dict[str, Any]:
    return {"id": p.id, "attempt": p.attempt, "strategy": p.strategy, "generator": p.generator,
            "rationale": p.rationale, "edits": p.edits, "diff": p.diff, "branch": p.branch, "base_sha": p.base_sha,
            "commit_sha": p.commit_sha, "status": p.status, "error": p.error, "usage": p.usage,
            "created_at": _ts(p.created_at)}


def validation(v: ValidationRun) -> dict[str, Any]:
    return {"id": v.id, "patch_id": v.patch_id, "status": v.status, "steps": v.steps,
            "started_at": _ts(v.started_at), "finished_at": _ts(v.finished_at)}


def approval(a: Approval) -> dict[str, Any]:
    return {"id": a.id, "patch_id": a.patch_id, "commit_sha": a.commit_sha, "decision": a.decision,
            "approver": a.approver, "comment": a.comment, "created_at": _ts(a.created_at)}


def audit_event(a: AuditEvent) -> dict[str, Any]:
    return {"id": a.id, "incident_id": a.incident_id, "timestamp": _ts(a.timestamp), "actor": a.actor,
            "action": a.action, "details": a.details}
