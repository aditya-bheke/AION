"""ORM models: the persistent state of AION.

Every stage of the incident workflow writes its output to its own table, so
the full history of an incident (what was observed, what the AI concluded,
what patch was produced, how it was validated, who approved it) can be
reconstructed later. See docs/notes/project/04-database.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aion.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Service(Base):
    """A monitored application that AION knows how to investigate and fix."""

    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    repo_path: Mapped[str] = mapped_column(String(500))
    production_branch: Mapped[str] = mapped_column(String(100), default="main")
    log_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Commands are stored as argv lists (no shell) - see validation/runner.py.
    test_command: Mapped[list] = mapped_column(JSON, default=list)
    run_command: Mapped[list] = mapped_column(JSON, default=list)
    health_path: Mapped[str] = mapped_column(String(200), default="/health")
    production_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    collector_offset: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class LogEvent(Base):
    __tablename__ = "log_events"
    __table_args__ = (Index("ix_log_service_time", "service_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    timestamp: Mapped[datetime]
    level: Mapped[str] = mapped_column(String(20))
    logger: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    template: Mapped[str] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(String(64), index=True)
    exception_type: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    exception_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stack_trace: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    frames: Mapped[list] = mapped_column(JSON, default=list)
    request: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(default=utcnow)


class LogSignature(Base):
    """One row per distinct log template per service: the deduplicated view."""

    __tablename__ = "log_signatures"
    __table_args__ = (UniqueConstraint("service_id", "signature"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    signature: Mapped[str] = mapped_column(String(64))
    level: Mapped[str] = mapped_column(String(20))
    template: Mapped[str] = mapped_column(Text)
    exception_type: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    first_seen: Mapped[datetime]
    last_seen: Mapped[datetime]
    count: Mapped[int] = mapped_column(Integer, default=0)
    sample_event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("log_events.id"), nullable=True)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(20), default="high")
    signature: Mapped[str] = mapped_column(String(64), index=True)
    detection_reason: Mapped[str] = mapped_column(Text, default="")
    first_seen: Mapped[datetime]
    last_seen: Mapped[datetime]
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    pipeline_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    service: Mapped[Service] = relationship()


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    environment: Mapped[str] = mapped_column(String(30), default="production")
    version: Mapped[str] = mapped_column(String(100))
    commit_sha: Mapped[str] = mapped_column(String(64))
    deployed_at: Mapped[datetime] = mapped_column(default=utcnow)
    deployed_by: Mapped[str] = mapped_column(String(100), default="ci")
    incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("incidents.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="succeeded")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CommitSuspect(Base):
    """A recent commit scored for how likely it is to have caused the incident."""

    __tablename__ = "commit_suspects"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    commit_sha: Mapped[str] = mapped_column(String(64))
    author: Mapped[str] = mapped_column(String(200))
    authored_at: Mapped[datetime]
    message: Mapped[str] = mapped_column(Text)
    files_changed: Mapped[list] = mapped_column(JSON, default=list)
    score: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    deployment_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class RCAReport(Base):
    __tablename__ = "rca_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    analyzer: Mapped[str] = mapped_column(String(200))
    probable_root_cause: Mapped[str] = mapped_column(Text)
    observed_evidence: Mapped[list] = mapped_column(JSON, default=list)
    inferences: Mapped[list] = mapped_column(JSON, default=list)
    affected_service: Mapped[str] = mapped_column(String(100))
    affected_files: Mapped[list] = mapped_column(JSON, default=list)
    suspected_commit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    remediation: Mapped[str] = mapped_column(Text)
    grounding_warnings: Mapped[list] = mapped_column(JSON, default=list)
    evidence_pack: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PatchProposal(Base):
    __tablename__ = "patch_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    strategy: Mapped[str] = mapped_column(String(40))  # "llm_edit" | "revert"
    generator: Mapped[str] = mapped_column(String(200))
    rationale: Mapped[str] = mapped_column(Text, default="")
    edits: Mapped[list] = mapped_column(JSON, default=list)
    diff: Mapped[str] = mapped_column(Text, default="")
    branch: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    base_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    commit_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    worktree_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="generated")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ValidationRun(Base):
    __tablename__ = "validation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    patch_id: Mapped[int] = mapped_column(ForeignKey("patch_proposals.id"))
    status: Mapped[str] = mapped_column(String(20), default="running")
    steps: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class Approval(Base):
    """A human decision on a specific, validated commit."""

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    patch_id: Mapped[int] = mapped_column(ForeignKey("patch_proposals.id"))
    commit_sha: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(20))  # approved | rejected
    approver: Mapped[str] = mapped_column(String(100))
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class User(Base):
    """A person who can sign in to AION. Roles: viewer < engineer < approver < admin."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class UserSession(Base):
    """A login session. Only a SHA-256 hash of the bearer token is stored."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    revoked: Mapped[bool] = mapped_column(default=False)


class AIProviderConfig(Base):
    """The AI provider chosen in the dashboard (single row). Overrides backend/.env when present."""

    __tablename__ = "ai_provider_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    preset: Mapped[str] = mapped_column(String(40))          # e.g. "anthropic", "openai", "ollama", "mcp"
    kind: Mapped[str] = mapped_column(String(30))            # "none" | "anthropic" | "openai_compat" | "mcp"
    model: Mapped[str] = mapped_column(String(200), default="")
    base_url: Mapped[str] = mapped_column(String(500), default="")
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # Fernet token
    api_key_hint: Mapped[str] = mapped_column(String(20), default="")
    effort: Mapped[str] = mapped_column(String(20), default="high")
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class AITask(Base):
    """A model call handed to an external AI agent through the MCP connector.

    The pipeline writes the exact system prompt, user prompt and JSON schema it would
    have sent to an API; a connected agent claims the task and submits JSON; the
    pipeline then validates and grounds that answer exactly as it would an API reply.
    """

    __tablename__ = "ai_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("incidents.id"), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(60))          # schema name: RCAOutput / PatchOutput / ...
    system_prompt: Mapped[str] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text)
    json_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending|claimed|answered|expired
    agent: Mapped[str] = mapped_column(String(100), default="")
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    answered_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class AuditEvent(Base):
    """Append-only audit trail. No API exists to update or delete rows."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("incidents.id"), nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(default=utcnow)
    actor: Mapped[str] = mapped_column(String(150))
    action: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
