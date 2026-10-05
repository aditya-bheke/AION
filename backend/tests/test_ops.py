"""Phase 6: notifications (outbox on the audit trail) and insights metrics."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from aion import notify
from aion.db import session_scope
from aion.main import create_app
from aion.models import NotificationChannel, NotificationDelivery
from aion.pipeline import orchestrator
from conftest import make_user
from test_end_to_end import _setup

SLACK_URL = "https://hooks.slack.example/services/T000/B000/SECRETPATH"


@pytest.fixture()
def client(aion_env, monkeypatch):
    monkeypatch.setattr("aion.api.incidents.enqueue_deploy", orchestrator.run_deploy)
    with TestClient(create_app(start_background=False)) as c:
        c.headers.update(make_user(c, "root", "admin"))
        yield c
    notify.set_transport(None)


def _capture(sent: list, fail_hosts=()):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in fail_hosts:
            return httpx.Response(500, text="boom")
        sent.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, text="ok")
    notify.set_transport(httpx.MockTransport(handler))


def test_channel_url_is_secret_and_admin_only(client):
    r = client.post("/api/notifications/channels", json={"name": "ops", "kind": "slack", "url": SLACK_URL})
    assert r.status_code == 200 and r.json()["url_hint"] == "https://hooks.slack.example/…"
    assert "SECRETPATH" not in client.get("/api/notifications/channels").text
    with session_scope() as s:
        assert "SECRETPATH" not in s.get(NotificationChannel, 1).url_encrypted  # encrypted at rest
    viewer = make_user(client, "vic", "viewer")
    assert client.post("/api/notifications/channels", headers=viewer,
                       json={"name": "x", "kind": "slack", "url": SLACK_URL}).status_code == 403
    assert client.post("/api/notifications/channels", json={"name": "x", "kind": "slack", "url": SLACK_URL,
                                                            "events": ["nonsense"]}).status_code == 422


def test_workflow_events_reach_subscribed_channels(client, demo_repo, tmp_path):
    sent = []
    _capture(sent, fail_hosts={"broken.example"})
    client.post("/api/notifications/channels", json={"name": "ops", "kind": "slack", "url": SLACK_URL,
                                                     "events": ["incident_detected", "awaiting_approval", "resolved"]})
    client.post("/api/notifications/channels", json={"name": "broken", "kind": "webhook",
                                                     "url": "https://broken.example/hook", "events": ["awaiting_approval"]})
    assert notify.deliver_pending() == 0  # first start: cursor set at the end, no flood of history

    repo_dir, commits, incident_id = _setup(client, demo_repo, tmp_path)
    orchestrator.run_pipeline(incident_id)
    notify.deliver_pending()
    texts = [body["text"] for url, body in sent]
    assert any(t.startswith("🚨 New incident") for t in texts)
    assert any(t.startswith("🔒 Fix ready") and f"/#/incidents/{incident_id}" in t for t in texts)
    assert not any("Fix deployed" in t for t in texts)  # not resolved yet

    client.post(f"/api/incidents/{incident_id}/approve", json={})
    client.post(f"/api/incidents/{incident_id}/deploy")
    notify.deliver_pending()
    assert any(body["text"].startswith("✅ Fix deployed") for _, body in sent)
    assert notify.deliver_pending() == 0  # nothing is sent twice

    with session_scope() as s:
        failed = [d for d in s.query(NotificationDelivery).all() if d.status == "failed"]
    assert failed and "500" in failed[0].error  # broken webhook logged, others still delivered


def test_insights_from_a_real_run(client, demo_repo, tmp_path):
    repo_dir, commits, incident_id = _setup(client, demo_repo, tmp_path)
    orchestrator.run_pipeline(incident_id)
    client.post(f"/api/incidents/{incident_id}/approve", json={})
    client.post(f"/api/incidents/{incident_id}/deploy")
    r = client.get("/api/insights").json()
    for k in ("mttd_s", "time_to_fix_s", "decision_s", "deploy_s", "mttr_s"):
        assert r["timings"][k]["count"] == 1 and r["timings"][k]["median"] is not None, k
    assert r["incidents_by_status"] == {"resolved": 1}
    assert r["patches_by_strategy"]["revert"]["deployed"] == 1
    assert r["incidents"][0]["mttr_s"] >= r["incidents"][0]["time_to_fix_s"]
