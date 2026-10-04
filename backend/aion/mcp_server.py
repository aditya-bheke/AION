"""AION MCP connector: lets an MCP-capable AI app act as AION's analyst.

Run by the AI app (stdio transport), for example in Claude Code:

    claude mcp add aion -- D:\\projects\\AION\\backend\\.venv\\Scripts\\python.exe -m aion.mcp_server

The server talks to a running AION over its REST API using AION_AGENT_TOKEN
(read from backend/.env). Tools:

    aion_list_incidents / aion_get_incident        - read-only context
    aion_list_pending_tasks / aion_get_task        - AI tasks waiting for an answer
    aion_submit_task_result                        - answer a task with JSON

How it fits: when the AI provider is set to "MCP connector", the pipeline turns
every model call (root-cause analysis, patch writing) into a task with the same
instructions, evidence and JSON schema it would send to an API, and waits. The
connected agent answers; AION then validates, grounds, sandboxes and tests the
answer exactly as it would an API reply.

There is deliberately no tool to approve, reject or deploy: production changes
need a signed-in human approver in the AION dashboard.

Note: with stdio transport stdout is the protocol channel - never print();
diagnostics go to stderr via logging.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from aion.config import settings  # loads backend/.env (AION_AGENT_TOKEN)

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s aion-mcp %(levelname)s %(message)s")
log = logging.getLogger("aion.mcp")

AION_URL = os.getenv("AION_URL", "http://127.0.0.1:8000").rstrip("/")

INSTRUCTIONS = """You are connected to AION, an incident-response platform, as its analyst.

Workflow:
1. Call aion_list_pending_tasks. Each task is one analysis AION needs (purpose RCAOutput = root-cause
   analysis, PatchOutput = a code fix).
2. Call aion_get_task(task_id). Follow its `instructions` exactly, study the evidence in `prompt`, and
   produce ONE JSON object that matches `json_schema`.
3. Call aion_submit_task_result(task_id, result_json). If AION reports a validation error, fix the JSON
   and submit again.
4. New tasks may appear afterwards (e.g. the patch after the root cause, or a retry with test
   feedback); repeat until none are pending.

Rules: cite only evidence IDs that exist in the prompt; keep observations separate from inferences;
never invent files or commits. You cannot approve or deploy anything - a human reviews every fix
in the AION dashboard."""

mcp = MCPServer(name="aion", title="AION incident analyst", instructions=INSTRUCTIONS, version="0.4.0")


def _client() -> httpx.Client:
    if not settings.agent_token:
        raise RuntimeError("AION_AGENT_TOKEN is not set. Run: python -m aion.cli agent-token --write "
                           "and restart AION.")
    return httpx.Client(base_url=AION_URL, timeout=30,
                        headers={"Authorization": f"Bearer {settings.agent_token}"})


def _call(method: str, path: str, **kwargs: Any) -> Any:
    try:
        with _client() as c:
            r = c.request(method, path, **kwargs)
    except httpx.ConnectError as exc:
        raise RuntimeError(f"AION is not reachable at {AION_URL} - is it running? ({exc})") from exc
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text
        raise RuntimeError(f"AION returned {r.status_code}: {detail}")
    return r.json()


READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


@mcp.tool(annotations=READ_ONLY)
def aion_list_incidents() -> list[dict]:
    """List recent AION incidents (id, status, title, service, first seen)."""
    return [{k: i[k] for k in ("id", "status", "title", "service", "first_seen", "event_count")}
            for i in _call("GET", "/api/agent/incidents")]


@mcp.tool(annotations=READ_ONLY)
def aion_get_incident(incident_id: int) -> dict:
    """Summary of one incident: status, root cause so far, patch attempts and the last validation result."""
    return _call("GET", f"/api/agent/incidents/{incident_id}")


@mcp.tool(annotations=READ_ONLY)
def aion_list_pending_tasks() -> list[dict]:
    """AI tasks waiting for an answer (oldest first). Purpose RCAOutput = root cause, PatchOutput = code fix."""
    return _call("GET", "/api/agent/tasks", params={"status": "open"})


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                                      open_world_hint=False))
def aion_get_task(task_id: int) -> dict:
    """Open (and claim) a task: returns the instructions, the evidence prompt and the JSON schema to answer with."""
    return _call("GET", f"/api/agent/tasks/{task_id}")


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False,
                                      open_world_hint=False))
def aion_submit_task_result(task_id: int, result_json: str, agent_name: str = "mcp-agent") -> dict:
    """Submit the answer to a task: ONE JSON object (as a string) matching the task's json_schema.

    AION validates it immediately; on a schema error you get the details and can resubmit. The answer is
    then grounded and (for patches) tested in a sandbox. Nothing is deployed without human approval.
    """
    return _call("POST", f"/api/agent/tasks/{task_id}/result", json={"result": result_json, "agent": agent_name})


def main() -> None:
    log.info("AION MCP connector starting (AION at %s)", AION_URL)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
