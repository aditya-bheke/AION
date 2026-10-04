"""MCP connector: an external agent answers AION's AI tasks; humans still approve."""
import asyncio
import os
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aion import mcp_server
from aion.ai.providers.factory import set_provider_override
from aion.ai.providers.mcp_bridge import MCPBridgeProvider
from aion.main import create_app
from aion.pipeline import orchestrator
from conftest import AGENT_HEADERS, SERVICE_HEADERS, make_user
from test_end_to_end import ScriptedLLM, _setup


@pytest.fixture()
def client(aion_env, monkeypatch):
    monkeypatch.setattr("aion.api.incidents.enqueue_deploy", orchestrator.run_deploy)
    with TestClient(create_app(start_background=False)) as c:
        c.headers.update(make_user(c, "aditya", "approver"))
        yield c


def _agent_loop(client, brain: ScriptedLLM, stop: threading.Event, answered: list):
    """Plays the connected AI app: list tasks -> read -> answer (through the real agent API)."""
    while not stop.is_set():
        for task in client.get("/api/agent/tasks", params={"status": "open"}, headers=AGENT_HEADERS).json():
            full = client.get(f"/api/agent/tasks/{task['task_id']}", headers=AGENT_HEADERS).json()
            reply = brain.complete_json(full["instructions"], full["prompt"], full["json_schema"], full["purpose"], 0)
            r = client.post(f"/api/agent/tasks/{task['task_id']}/result", headers=AGENT_HEADERS,
                            json={"result": reply.text, "agent": "test-agent"})
            answered.append((full["purpose"], r.status_code))
        time.sleep(0.05)


def test_pipeline_answered_by_mcp_agent_still_needs_a_human(client, demo_repo, tmp_path):
    repo_dir, commits, incident_id = _setup(client, demo_repo, tmp_path)
    buggy = next(c for c in commits if c.message.startswith("Support seasonal campaigns"))
    set_provider_override(MCPBridgeProvider(timeout_seconds=120, poll_seconds=0.05))
    stop, answered = threading.Event(), []
    agent = threading.Thread(target=_agent_loop, args=(client, ScriptedLLM(buggy.sha), stop, answered), daemon=True)
    agent.start()
    try:
        orchestrator.run_pipeline(incident_id)
    finally:
        stop.set()
        agent.join(5)

    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["incident"]["status"] == "awaiting_approval", detail["incident"]["pipeline_error"]
    assert [p for p, _ in answered] == ["RCAOutput", "PatchOutput"] and all(c == 200 for _, c in answered)
    assert detail["rca"]["analyzer"] == "mcp:connected-agent"
    assert detail["patches"][-1]["strategy"] == "llm_edit" and detail["patches"][-1]["status"] == "passed"
    assert all(t["status"] == "answered" and t["agent"] == "test-agent" for t in detail["ai_tasks"])
    assert any(a["actor"] == "ai:test-agent" and a["action"] == "ai_task_answered" for a in detail["audit"])

    # The agent has no way to approve or deploy: those endpoints don't accept its token.
    assert client.post(f"/api/incidents/{incident_id}/approve", json={}, headers=AGENT_HEADERS).status_code == 401
    assert client.post(f"/api/incidents/{incident_id}/deploy", headers=AGENT_HEADERS).status_code == 401
    assert client.post(f"/api/incidents/{incident_id}/approve", json={"comment": "reviewed"}).status_code == 200


def test_agent_endpoints_accept_only_the_agent_token(client):
    assert client.get("/api/agent/tasks").status_code == 401                         # signed-in human: not an agent
    assert client.get("/api/agent/tasks", headers=SERVICE_HEADERS).status_code == 401
    assert client.get("/api/agent/tasks", headers=AGENT_HEADERS).status_code == 200
    assert client.post("/api/ingest/x", json={"events": []}, headers=AGENT_HEADERS).status_code == 401


def test_invalid_answers_are_rejected_and_the_task_stays_open(client, aion_env):
    from aion.db import session_scope
    from aion.models import AITask

    with session_scope() as s:
        s.add(AITask(purpose="RCAOutput", system_prompt="sys", prompt="p", json_schema={}, status="pending"))
    r = client.post("/api/agent/tasks/1/result", headers=AGENT_HEADERS, json={"result": "not json"})
    assert r.status_code == 422
    r = client.post("/api/agent/tasks/1/result", headers=AGENT_HEADERS, json={"result": '{"probable_root_cause": 1}'})
    assert r.status_code == 422 and "RCAOutput" in r.text
    assert client.get("/api/agent/tasks", headers=AGENT_HEADERS).json()[0]["status"] == "pending"


def test_no_agent_times_out_and_falls_back_to_deterministic_analysis(client, demo_repo, tmp_path):
    repo_dir, commits, incident_id = _setup(client, demo_repo, tmp_path)
    set_provider_override(MCPBridgeProvider(timeout_seconds=1, poll_seconds=0.05))
    orchestrator.run_pipeline(incident_id)
    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["rca"]["analyzer"] == "heuristic (no LLM)"
    assert any("No AI agent answered" in w for w in detail["rca"]["grounding_warnings"])
    assert detail["ai_tasks"][0]["status"] == "expired"
    assert detail["incident"]["status"] == "awaiting_approval"  # revert path, still human-gated


def test_mcp_tools_call_aion_with_the_agent_token(client, monkeypatch):
    agent_client = TestClient(client.app, headers=AGENT_HEADERS)
    monkeypatch.setattr(mcp_server, "_client", lambda: agent_client)
    assert mcp_server.aion_list_incidents() == []
    assert mcp_server.aion_list_pending_tasks() == []
    with pytest.raises(RuntimeError, match="404"):
        mcp_server.aion_get_task(999)


def test_stdio_server_speaks_mcp():
    """Start the real server process and talk MCP to it over stdio."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    backend = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(command=sys.executable, args=["-m", "aion.mcp_server"], cwd=str(backend),
                                   env={**os.environ, "AION_AGENT_TOKEN": "x"})

    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                return init, {t.name for t in tools.tools}

    init, names = asyncio.run(run())
    assert init.server_info.name == "aion"
    assert names == {"aion_list_incidents", "aion_get_incident", "aion_list_pending_tasks", "aion_get_task",
                     "aion_submit_task_result"}
    assert not any("approve" in n or "deploy" in n for n in names)
