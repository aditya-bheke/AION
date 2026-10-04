"""Pydantic models for API request bodies (validation at the HTTP boundary)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    repo_path: str
    production_branch: str = "main"
    log_path: Optional[str] = None
    test_command: list[str] = Field(default_factory=lambda: ["{python}", "-m", "pytest", "-q"])
    run_command: list[str] = Field(default_factory=list,
                                   description="argv to start the service; may use {python} and {port}")
    health_path: str = "/health"
    production_url: Optional[str] = None


class IngestIn(BaseModel):
    events: list[dict[str, Any]] = Field(max_length=5000)


class DeploymentIn(BaseModel):
    service: str
    version: str
    commit_sha: str = Field(min_length=7, max_length=64)
    environment: str = "production"
    deployed_at: Optional[datetime] = None
    deployed_by: str = "ci"
    notes: Optional[str] = None


class DecisionIn(BaseModel):
    approver: str = Field(min_length=2, max_length=100)
    comment: str = Field(default="", max_length=2000)


class ActorIn(BaseModel):
    actor: str = Field(min_length=2, max_length=100)
