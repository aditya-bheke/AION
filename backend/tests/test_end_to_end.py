"""Full workflow against a real git repository and the real demo service.

detection -> correlation -> RCA -> patch -> validation (tests + staging replay)
-> human approval gate -> deployment (fast-forward of main) -> resolved.
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from aion.ai.providers.base import LLMResponse
from aion.ai.providers.factory import set_provider_override
from aion.config import settings
from aion.db import session_scope
from aion.gitops.repo import GitRepo
from aion.main import create_app
from aion.models import Incident
from aion.pipeline import orchestrator
from conftest import SERVICE_HEADERS, generate_service_logs, make_user


@pytest.fixture()
def client(aion_env, monkeypatch):
    # Run deployments synchronously in tests instead of on the worker thread.
    monkeypatch.setattr("aion.api.incidents.enqueue_deploy", orchestrator.run_deploy)
    with TestClient(create_app(start_background=False)) as c:
        # Default identity for reads and decisions: a signed-in approver.
        c.headers.update(make_user(c, "aditya", "approver"))
        yield c


def _setup(client, demo_repo, tmp_path, mutate=None):
    repo_dir, commits = demo_repo
    r = client.post("/api/services", headers=SERVICE_HEADERS, json={
        "name": "orders-service", "repo_path": str(repo_dir),
        "test_command": ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        "run_command": ["{python}", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "{port}"],
    })
    assert r.status_code == 200, r.text
    for c in commits:
        if c.deploy_version:
            assert client.post("/api/deployments", headers=SERVICE_HEADERS, json={
                "service": "orders-service", "version": c.deploy_version, "commit_sha": c.sha,
                "deployed_at": c.deployed_at.isoformat()}).status_code == 200
    events = generate_service_logs(repo_dir, tmp_path / "prod.log")
    if mutate:
        mutate(events)
    r = client.post("/api/ingest/orders-service", headers=SERVICE_HEADERS, json={"events": events})
    assert r.status_code == 200
    body = r.json()
    assert len(body["new_incidents"]) == 1
    return repo_dir, commits, body["new_incidents"][0]


def test_heuristic_workflow_requires_human_approval(client, demo_repo, tmp_path):
    repo_dir, commits, incident_id = _setup(client, demo_repo, tmp_path)
    buggy = next(c for c in commits if c.message.startswith("Support seasonal campaigns"))

    orchestrator.run_pipeline(incident_id)
    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["incident"]["status"] == "awaiting_approval", detail["incident"]["pipeline_error"]
    assert detail["suspects"][0]["commit_sha"] == buggy.sha
    assert detail["rca"]["analyzer"] == "heuristic (no LLM)"
    assert detail["rca"]["suspected_commit"] == buggy.sha
    patch = detail["patches"][-1]
    assert patch["strategy"] == "revert" and patch["status"] == "passed"
    steps = {s["name"]: s["status"] for s in detail["validations"][-1]["steps"]}
    assert steps["unit_tests"] == "passed"
    assert steps["staging_deploy"] == "passed"
    assert steps["replay_requests"] == "passed"

    # Production has not changed: AION stops at the approval gate.
    git = GitRepo(repo_dir)
    assert git.rev_parse("main") == commits[-1].sha
    assert client.post(f"/api/incidents/{incident_id}/deploy").status_code == 409

    r = client.post(f"/api/incidents/{incident_id}/approve", json={"comment": "LGTM"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    r = client.post(f"/api/incidents/{incident_id}/deploy")
    assert r.status_code == 200

    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["incident"]["status"] == "resolved", detail["incident"]["pipeline_error"]
    assert git.rev_parse("main") == patch["commit_sha"]
    actions = [(a["actor"], a["action"]) for a in detail["audit"]]
    assert ("human:aditya", "status_changed") in actions
    assert any(a == "deployment_completed" for _, a in actions)
    assert detail["deployments"][0]["deployed_by"] == "human:aditya"

    # A resolved incident cannot be approved or deployed again.
    assert client.post(f"/api/incidents/{incident_id}/approve", json={}).status_code == 409


class ScriptedLLM:
    """Test double standing in for a real model: replies are scripted per task."""

    name = "scripted:test-model"

    def __init__(self, buggy_sha):
        self.buggy_sha = buggy_sha
        self.calls = []

    def complete_json(self, system, user, schema, schema_name, max_tokens):
        self.calls.append((schema_name, user))
        if schema_name == "RCAOutput":
            return LLMResponse(json.dumps({
                "probable_root_cause": "get_coupon() now returns None for expired codes; apply_discount() indexes it.",
                "observed_evidence": [{"evidence_id": "TRACE-1", "observation": "TypeError in apply_discount"},
                                      {"evidence_id": f"COMMIT-{self.buggy_sha[:7]}", "observation": "changed get_coupon"}],
                "inferences": [{"statement": "Expired coupons crash pricing", "based_on": ["TRACE-1"]}],
                "affected_service": "orders-service", "affected_files": ["app/pricing.py"],
                "suspected_commit": self.buggy_sha[:7], "confidence": 0.9, "confidence_rationale": "diff + trace",
                "remediation": "Treat unknown/expired coupons as a 400 client error.",
                "alternative_hypotheses": []}))
        return LLMResponse(json.dumps({
            "summary": "Reject unknown or expired coupons with HTTP 400",
            "rationale": "get_coupon returns None for invalid codes; handle it before applying the discount.",
            "edits": [
                {"path": "app/pricing.py",
                 "search": "        coupon = coupons.get_coupon(coupon_code)\n",
                 "replace": "        coupon = coupons.get_coupon(coupon_code)\n"
                            "        if coupon is None:\n"
                            "            raise InvalidCoupon(coupon_code)\n"},
                {"path": "app/pricing.py",
                 "search": "GST_RATE = 0.18\n",
                 "replace": "GST_RATE = 0.18\n\n\nclass InvalidCoupon(ValueError):\n    pass\n"},
                {"path": "app/main.py",
                 "search": "    return pricing.compute_total(order, coupon)\n",
                 "replace": "    try:\n        return pricing.compute_total(order, coupon)\n"
                            "    except pricing.InvalidCoupon:\n"
                            "        raise HTTPException(status_code=400, detail=f\"Coupon {coupon} is invalid or expired\")\n"},
            ],
            "new_test_files": [{"path": "tests/test_aion_expired_coupon.py", "content":
                                "from fastapi.testclient import TestClient\nfrom app.main import app\n\n\n"
                                "def test_expired_coupon_is_client_error():\n"
                                "    r = TestClient(app, raise_server_exceptions=False).get('/orders/1002/total?coupon=SUMMER23')\n"
                                "    assert r.status_code == 400\n"}],
            "risk_notes": "Clients sending invalid coupons now get 400 instead of 500."}))


def _add_customer_pii(events):
    """Make the failing requests carry personal data, as real query strings often do."""
    for e in events:
        if e.get("request") and "SUMMER23" in e["request"].get("query", ""):
            e["request"]["query"] += "&email=priya.sharma@example.com"


def test_llm_workflow_produces_validated_fix_with_regression_test(client, demo_repo, tmp_path):
    repo_dir, commits, incident_id = _setup(client, demo_repo, tmp_path, mutate=_add_customer_pii)
    buggy = next(c for c in commits if c.message.startswith("Support seasonal campaigns"))
    llm = ScriptedLLM(buggy.sha)
    set_provider_override(llm)

    orchestrator.run_pipeline(incident_id)
    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["incident"]["status"] == "awaiting_approval", detail["incident"]["pipeline_error"]
    assert [c[0] for c in llm.calls] == ["RCAOutput", "PatchOutput"]
    # The model received curated evidence, not raw logs.
    rca_prompt = llm.calls[0][1]
    assert "[TRACE-1]" in rca_prompt and f"[COMMIT-{buggy.sha[:7]}]" in rca_prompt and "[CODE-1]" in rca_prompt
    # Personal data never reaches the model, and the redaction is recorded.
    assert all("priya.sharma@example.com" not in prompt for _, prompt in llm.calls)
    assert "[REDACTED:email]" in rca_prompt
    assert detail["rca"]["evidence_pack"]["redactions"]["email"] >= 1
    assert detail["rca"]["suspected_commit"] == buggy.sha  # short SHA expanded by grounding
    patch = detail["patches"][-1]
    assert patch["strategy"] == "llm_edit"
    steps = {s["name"]: s["status"] for s in detail["validations"][-1]["steps"]}
    assert steps == {"syntax_check": "passed", "regression_reproduce": "passed", "unit_tests": "passed",
                     "staging_deploy": "passed", "replay_requests": "passed"}
    replay = next(s for s in detail["validations"][-1]["steps"] if s["name"] == "replay_requests")
    assert any(r["kind"] == "incident" and r["status"] == 400 for r in replay["details"]["results"])


class BadPatchLLM(ScriptedLLM):
    """Correct RCA, but every patch breaks the module."""

    def complete_json(self, system, user, schema, schema_name, max_tokens):
        if schema_name == "RCAOutput":
            return super().complete_json(system, user, schema, schema_name, max_tokens)
        self.calls.append((schema_name, user))
        return LLMResponse(json.dumps({
            "summary": "broken", "rationale": "", "risk_notes": "", "new_test_files": [],
            "edits": [{"path": "app/pricing.py", "search": "GST_RATE = 0.18\n", "replace": "GST_RATE = (\n"}]}))


def test_failed_validation_never_reaches_approval(client, demo_repo, tmp_path, monkeypatch):
    repo_dir, commits, incident_id = _setup(client, demo_repo, tmp_path)
    buggy = next(c for c in commits if c.message.startswith("Support seasonal campaigns"))
    monkeypatch.setattr(settings, "revert_fallback", False)

    set_provider_override(BadPatchLLM(buggy.sha))
    orchestrator.run_pipeline(incident_id)
    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["incident"]["status"] == "validation_failed"
    assert len(detail["patches"]) == 2  # one repair attempt with failure feedback
    assert "failed" in detail["validations"][-1]["steps"][0]["status"]
    assert client.post(f"/api/incidents/{incident_id}/approve", json={}).status_code == 409
    with session_scope() as s:
        assert s.scalar(select(Incident.status).where(Incident.id == incident_id)) == "validation_failed"


def test_revert_fallback_after_failed_ai_patches_still_needs_approval(client, demo_repo, tmp_path):
    repo_dir, commits, incident_id = _setup(client, demo_repo, tmp_path)
    buggy = next(c for c in commits if c.message.startswith("Support seasonal campaigns"))
    set_provider_override(BadPatchLLM(buggy.sha))

    orchestrator.run_pipeline(incident_id)
    detail = client.get(f"/api/incidents/{incident_id}").json()
    patches = detail["patches"]
    assert [p["strategy"] for p in patches] == ["llm_edit", "llm_edit", "revert"]
    assert [p["status"] for p in patches] == ["failed", "failed", "passed"]
    assert "fallback after 2 failed AI attempts" in patches[-1]["generator"]
    assert detail["incident"]["status"] == "awaiting_approval"  # still a human decision
    assert any(a["action"] == "revert_fallback" for a in detail["audit"])
    assert GitRepo(repo_dir).rev_parse("main") == commits[-1].sha  # production untouched


def _deploy_heuristic_fix(client, demo_repo, tmp_path):
    repo_dir, commits, incident_id = _setup(client, demo_repo, tmp_path)
    orchestrator.run_pipeline(incident_id)
    assert client.post(f"/api/incidents/{incident_id}/approve", json={"comment": "ok"}).status_code == 200
    return repo_dir, commits, incident_id


def test_manual_rollback_reverts_the_fix_and_reopens(client, demo_repo, tmp_path, monkeypatch):
    monkeypatch.setattr("aion.api.incidents.enqueue_rollback", orchestrator.run_rollback)
    repo_dir, commits, incident_id = _deploy_heuristic_fix(client, demo_repo, tmp_path)
    client.post(f"/api/incidents/{incident_id}/deploy")
    git = GitRepo(repo_dir)
    fix = git.rev_parse("main")
    assert client.get(f"/api/incidents/{incident_id}").json()["incident"]["status"] == "resolved"

    viewer = make_user(client, "vic", "viewer")
    assert client.post(f"/api/incidents/{incident_id}/rollback", json={}, headers=viewer).status_code == 403
    r = client.post(f"/api/incidents/{incident_id}/rollback", json={"comment": "fix caused complaints"})
    assert r.status_code == 200

    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["incident"]["status"] == "rolled_back"
    head = git.rev_parse("main")
    assert head != fix and git.git("diff", commits[-1].sha, head).strip() == ""  # back to the pre-fix tree
    assert "Revert" in git.git("log", "-1", "--format=%s", head)  # history kept, rollback is a commit
    rb = [d for d in detail["deployments"] if d["version"].startswith("rollback-")][0]
    assert rb["deployed_by"] == "human:aditya" and rb["commit_sha"] == head
    assert any(a["action"] == "rollback_completed" for a in detail["audit"])
    # Rolled back = open again: the investigation can be re-run.
    assert client.post(f"/api/incidents/{incident_id}/rerun").status_code == 200


def test_failed_production_verification_rolls_back_automatically(client, demo_repo, tmp_path, monkeypatch):
    monkeypatch.setattr("aion.deploy.deployer.verify_production",
                        lambda *a, **k: (False, "simulated: production unhealthy after deploy", []))
    repo_dir, commits, incident_id = _deploy_heuristic_fix(client, demo_repo, tmp_path)
    client.post(f"/api/incidents/{incident_id}/deploy")
    detail = client.get(f"/api/incidents/{incident_id}").json()
    statuses = [a["details"].get("to_status") for a in detail["audit"] if a["action"] == "status_changed"]
    assert statuses[-3:] == ["deploy_failed", "rolling_back", "rolled_back"]
    assert git_tree_equal(GitRepo(repo_dir), commits[-1].sha, "main")
    assert any(a["actor"] == "system:auto-rollback" and a["action"] == "rollback_completed" for a in detail["audit"])


def git_tree_equal(git, a, b):
    return git.git("diff", a, b).strip() == ""
