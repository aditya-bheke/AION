"""Endpoints for AI agents connected through the MCP connector (aion.mcp_server).

Authenticated with AION_AGENT_TOKEN. An agent can: list and read AI tasks,
submit an answer, and read incident summaries. It cannot approve, reject,
deploy, ingest or change configuration - those endpoints require a human or the
service token.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from aion import audit
from aion.ai.patcher import PatchOutput
from aion.ai.providers.base import extract_json
from aion.ai.rca import RCAOutput
from aion.api import serializers as ser
from aion.db import get_session
from aion.models import AITask, Incident, PatchProposal, RCAReport, Service, ValidationRun, utcnow
from aion.security import Principal, require_agent

router = APIRouter(prefix="/api/agent", tags=["mcp-agent"])

# Schemas the pipeline asks for; answers are validated before they are accepted.
SCHEMAS = {"RCAOutput": RCAOutput, "PatchOutput": PatchOutput}

_seen_lock = threading.Lock()
_last_seen: Optional[float] = None


def last_agent_seen() -> Optional[float]:
    with _seen_lock:
        return _last_seen


def _touch(_: Principal = Depends(require_agent)) -> Principal:
    global _last_seen
    with _seen_lock:
        _last_seen = time.time()
    return _


class ResultIn(BaseModel):
    result: str = Field(min_length=2, max_length=200_000, description="The JSON answer, as text")
    agent: str = Field(default="mcp-agent", max_length=100, description="Name of the agent/model answering")


def _task_summary(t: AITask) -> dict:
    return {"task_id": t.id, "incident_id": t.incident_id, "purpose": t.purpose, "status": t.status,
            "created_at": ser._ts(t.created_at)}


@router.get("/tasks")
def list_tasks(status: str = "pending", session: Session = Depends(get_session), _: Principal = Depends(_touch)):
    statuses = ["pending", "claimed"] if status == "open" else [status]
    rows = session.scalars(select(AITask).where(AITask.status.in_(statuses)).order_by(AITask.id)).all()
    return [_task_summary(t) for t in rows]


@router.get("/tasks/{task_id}")
def get_task(task_id: int, session: Session = Depends(get_session), agent: Principal = Depends(_touch)):
    """Read (and claim) a task: the exact instructions, evidence and JSON schema."""
    t = session.get(AITask, task_id)
    if t is None:
        raise HTTPException(404, "Task not found")
    if t.status == "pending":
        t.status, t.claimed_at = "claimed", utcnow()
        audit.record(session, "ai_task_claimed", agent.actor, incident_id=t.incident_id, task_id=t.id,
                     purpose=t.purpose)
    return {**_task_summary(t), "instructions": t.system_prompt, "prompt": t.prompt, "json_schema": t.json_schema,
            "how_to_answer": "Reply by submitting ONE JSON object that matches json_schema exactly "
                             "(no markdown, no prose) with aion_submit_task_result."}


@router.post("/tasks/{task_id}/result")
def submit_result(task_id: int, body: ResultIn, session: Session = Depends(get_session),
                  agent: Principal = Depends(_touch)):
    t = session.get(AITask, task_id)
    if t is None:
        raise HTTPException(404, "Task not found")
    if t.status not in ("pending", "claimed"):
        raise HTTPException(409, f"Task is already {t.status}")
    # Validate before accepting, so the agent can correct itself immediately.
    try:
        data = extract_json(body.result)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"Result is not valid JSON: {exc}")
    model = SCHEMAS.get(t.purpose)
    if model is not None:
        try:
            model.model_validate(data)
        except ValidationError as exc:
            raise HTTPException(422, f"Result does not match the {t.purpose} schema: {str(exc)[:1500]}")
    t.response, t.status, t.answered_at, t.agent = json.dumps(data), "answered", utcnow(), body.agent
    audit.record(session, "ai_task_answered", f"ai:{body.agent}", incident_id=t.incident_id, task_id=t.id,
                 purpose=t.purpose)
    return {"accepted": True, "note": "AION will now validate and ground this answer. A human approves any fix."}


@router.get("/incidents")
def agent_incidents(session: Session = Depends(get_session), _: Principal = Depends(_touch)):
    rows = session.execute(select(Incident, Service.name).join(Service).order_by(Incident.id.desc()).limit(50))
    return [ser.incident(i, name) for i, name in rows]


@router.get("/incidents/{incident_id}")
def agent_incident(incident_id: int, session: Session = Depends(get_session), _: Principal = Depends(_touch)):
    inc = session.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(404, "Incident not found")
    rca = session.scalar(select(RCAReport).where(RCAReport.incident_id == inc.id).order_by(RCAReport.id.desc()))
    patches = session.scalars(select(PatchProposal).where(PatchProposal.incident_id == inc.id)
                              .order_by(PatchProposal.id)).all()
    runs = session.scalars(select(ValidationRun).where(ValidationRun.incident_id == inc.id)
                           .order_by(ValidationRun.id)).all()
    return {
        "incident": ser.incident(inc, session.get(Service, inc.service_id).name),
        "root_cause": rca.probable_root_cause if rca else None,
        "confidence": rca.confidence if rca else None,
        "analyzer": rca.analyzer if rca else None,
        "patches": [{"attempt": p.attempt, "strategy": p.strategy, "status": p.status, "error": p.error,
                     "diff": p.diff[:4000]} for p in patches],
        "last_validation": [{"step": s["name"], "status": s["status"], "summary": s["summary"]}
                            for s in (runs[-1].steps if runs else [])],
        "note": "Approval and deployment are human-only and are not available to agents.",
    }
