"""Authentication, roles, service token, brute-force lockout and the two-person rule."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from aion import security
from aion.config import settings
from aion.db import session_scope
from aion.deploy.deployer import DeploymentBlocked, preflight
from aion.main import create_app
from aion.models import Incident, PatchProposal, Service, UserSession, ValidationRun, utcnow
from conftest import SERVICE_HEADERS, make_user


@pytest.fixture()
def client(aion_env, monkeypatch):
    monkeypatch.setattr("aion.api.incidents.enqueue_deploy", lambda *a, **k: True)
    monkeypatch.setattr("aion.api.incidents.enqueue_pipeline", lambda *a, **k: True)
    with TestClient(create_app(start_background=False)) as c:
        yield c


def _incident_awaiting_approval() -> int:
    """Minimal DB state: an incident with a validated patch, ready for approval."""
    with session_scope() as s:
        svc = Service(name="svc", repo_path=".")
        s.add(svc)
        s.flush()
        inc = Incident(service_id=svc.id, title="t", status="awaiting_approval", signature="x",
                       first_seen=utcnow(), last_seen=utcnow())
        s.add(inc)
        s.flush()
        patch = PatchProposal(incident_id=inc.id, strategy="revert", generator="g", status="passed",
                              commit_sha="a" * 40, base_sha="b" * 40, branch="aion/x")
        s.add(patch)
        s.flush()
        s.add(ValidationRun(incident_id=inc.id, patch_id=patch.id, status="passed"))
        return inc.id


# ---- passwords & sessions ---------------------------------------------------------------
def test_password_hash_is_salted_and_verifiable():
    h1, h2 = security.hash_password("correct horse battery", 1000), security.hash_password("correct horse battery", 1000)
    assert h1 != h2 and h1.startswith("pbkdf2_sha256$1000$")
    assert security.verify_password("correct horse battery", h1)
    assert not security.verify_password("wrong password!", h1)


def test_short_passwords_are_rejected(aion_env):
    with session_scope() as s, pytest.raises(ValueError):
        security.create_user(s, "bob", "short", "viewer")


def test_login_returns_token_but_only_its_hash_is_stored(client):
    headers = make_user(client, "vic", "viewer")
    token = headers["Authorization"].split()[1]
    with session_scope() as s:
        stored = [row.token_hash for row in s.scalars(select(UserSession))]
    assert token not in stored and len(stored[0]) == 64
    assert client.get("/api/auth/me", headers=headers).json()["role"] == "viewer"


def test_wrong_password_and_lockout(client):
    make_user(client, "vic", "viewer")
    for _ in range(security.MAX_FAILED_LOGINS):
        assert client.post("/api/auth/login", json={"username": "vic", "password": "nope-nope-nope"}).status_code == 401
    # Even the right password is refused while locked out.
    r = client.post("/api/auth/login", json={"username": "vic", "password": "correct horse battery"})
    assert r.status_code == 429


def test_logout_and_disabled_users_lose_access(client):
    headers = make_user(client, "vic", "viewer")
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/incidents", headers=headers).status_code == 401
    headers = make_user(client, "dan", "viewer")
    with session_scope() as s:
        s.scalar(select(security.User).where(security.User.username == "dan")).active = False
    assert client.get("/api/incidents", headers=headers).status_code == 401


# ---- authorisation ---------------------------------------------------------------------------
def test_reads_require_sign_in(client):
    assert client.get("/api/incidents").status_code == 401
    assert client.get("/api/audit").status_code == 401
    assert client.get("/api/health").status_code == 200  # liveness stays public


def test_roles_are_enforced(client):
    inc = _incident_awaiting_approval()
    viewer = make_user(client, "vic", "viewer")
    engineer = make_user(client, "eve", "engineer")
    assert client.post(f"/api/incidents/{inc}/approve", json={}, headers=viewer).status_code == 403
    assert client.post(f"/api/incidents/{inc}/approve", json={}, headers=engineer).status_code == 403
    assert client.post(f"/api/incidents/{inc}/deploy", headers=engineer).status_code == 403
    approver = make_user(client, "aditya", "approver")
    r = client.post(f"/api/incidents/{inc}/approve", json={"comment": "ok"}, headers=approver)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    audit = client.get(f"/api/audit?incident_id={inc}", headers=viewer).json()
    assert any(a["actor"] == "human:aditya" for a in audit)  # identity from the session, not the body


def test_machine_endpoints_need_the_service_token(client):
    body = {"events": [{"level": "INFO", "message": "x"}]}
    assert client.post("/api/ingest/svc", json=body).status_code == 401
    assert client.post("/api/ingest/svc", json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
    approver = make_user(client, "aditya", "approver")
    assert client.post("/api/ingest/svc", json=body, headers=approver).status_code == 401  # users are not machines
    assert client.post("/api/ingest/svc", json=body, headers=SERVICE_HEADERS).status_code == 404  # authorised; unknown svc
    admin = make_user(client, "root", "admin")
    assert client.post("/api/ingest/svc", json=body, headers=admin).status_code == 404


def test_machine_endpoints_disabled_without_configured_token(client, monkeypatch):
    monkeypatch.setattr(settings, "service_token", "")
    assert client.post("/api/ingest/svc", json={"events": []}, headers={"Authorization": "Bearer "}).status_code == 401


# ---- two-person rule ---------------------------------------------------------------------------
def test_two_person_rule(client, monkeypatch):
    monkeypatch.setattr(settings, "required_approvals", 2)
    inc = _incident_awaiting_approval()
    a1 = make_user(client, "aditya", "approver")
    a2 = make_user(client, "riya", "approver")

    r = client.post(f"/api/incidents/{inc}/approve", json={"comment": "first"}, headers=a1)
    assert r.json() == {"status": "awaiting_approval", "approvals": 1, "required": 2}
    assert client.post(f"/api/incidents/{inc}/approve", json={}, headers=a1).status_code == 409  # same person twice
    assert client.post(f"/api/incidents/{inc}/deploy", headers=a1).status_code == 409           # not approved yet

    r = client.post(f"/api/incidents/{inc}/approve", json={"comment": "second"}, headers=a2)
    assert r.json()["status"] == "approved"
    assert client.post(f"/api/incidents/{inc}/deploy", headers=a2).status_code == 200


def test_deployer_independently_enforces_required_approvals(client, monkeypatch):
    inc_id = _incident_awaiting_approval()
    a1 = make_user(client, "aditya", "approver")
    client.post(f"/api/incidents/{inc_id}/approve", json={}, headers=a1)
    monkeypatch.setattr(settings, "required_approvals", 2)  # policy tightened after approval
    with session_scope() as s:
        inc = s.get(Incident, inc_id)
        patch = s.scalar(select(PatchProposal).where(PatchProposal.incident_id == inc_id))
        with pytest.raises(DeploymentBlocked, match="1 of 2"):
            preflight(s, inc, patch)
