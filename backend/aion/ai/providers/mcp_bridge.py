"""The MCP connector seen from the pipeline: an LLMProvider answered by an external agent.

Instead of calling a model API, `complete_json` stores the request as an
AITask row and waits. An AI agent connected to AION's MCP server
(`python -m aion.mcp_server`, e.g. Claude Code or Claude Desktop) lists the
pending task, reads the same system prompt / evidence / JSON schema an API
model would get, and submits its JSON answer. From there everything is
unchanged: `generate_structured` validates the JSON (and asks again through a
new task if it is invalid), grounding checks the claims, policy and
validation check the patch, and a human approves.

The agent never gets a tool to approve or deploy.
"""
from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Any, Optional

from aion.ai.providers.base import LLMError, LLMResponse
from aion.config import settings
from aion.db import session_scope
from aion.models import AITask, utcnow

# Set by the orchestrator so tasks can be linked to their incident in the dashboard.
current_incident: ContextVar[Optional[int]] = ContextVar("current_incident", default=None)

POLL_SECONDS = 1.0


class MCPBridgeProvider:
    name = "mcp:connected-agent"

    def __init__(self, timeout_seconds: Optional[int] = None, poll_seconds: float = POLL_SECONDS):
        self.timeout = timeout_seconds or settings.mcp_task_timeout_seconds
        self.poll = poll_seconds

    def complete_json(self, system: str, user: str, schema: dict[str, Any], schema_name: str,
                      max_tokens: int) -> LLMResponse:
        with session_scope() as s:
            task = AITask(incident_id=current_incident.get(), purpose=schema_name, system_prompt=system,
                          prompt=user, json_schema=schema, status="pending")
            s.add(task)
            s.flush()
            task_id = task.id
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            time.sleep(self.poll)
            with session_scope() as s:
                task = s.get(AITask, task_id)
                if task.status == "answered":
                    return LLMResponse(text=task.response or "", usage={"agent": task.agent, "model": self.name})
        with session_scope() as s:
            task = s.get(AITask, task_id)
            if task.status == "answered":  # answered in the last instant
                return LLMResponse(text=task.response or "", usage={"agent": task.agent, "model": self.name})
            task.status = "expired"
            task.answered_at = utcnow()
        raise LLMError(f"No AI agent answered task #{task_id} ({schema_name}) through the MCP connector "
                       f"within {self.timeout}s")
