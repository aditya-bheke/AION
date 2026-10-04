"""Choosing the AI provider in the dashboard: presets, encrypted API keys, admin-only changes."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from aion.ai.providers.factory import get_provider, invalidate_cache
from aion.config import settings
from aion.db import session_scope
from aion.main import create_app
from aion.models import AIProviderConfig, AuditEvent
from conftest import make_user

KEY = "sk-ant-api03-THIS-IS-A-FAKE-TEST-KEY-1234abcd"


@pytest.fixture()
def client(aion_env):
    invalidate_cache()
    with TestClient(create_app(start_background=False)) as c:
        c.headers.update(make_user(c, "root", "admin"))
        yield c
    invalidate_cache()


def test_presets_include_api_local_and_mcp(client):
    ids = {p["id"] for p in client.get("/api/ai/presets").json()}
    assert {"none", "anthropic", "openai", "groq", "openrouter", "gemini", "ollama", "lmstudio", "custom", "mcp"} <= ids


def test_api_key_is_encrypted_and_never_returned(client):
    r = client.put("/api/ai/config", json={"preset": "anthropic", "api_key": KEY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "dashboard" and body["model"] == "claude-opus-5-5" and body["api_key_hint"] == "…abcd"
    assert KEY not in r.text and KEY not in client.get("/api/ai/config").text
    with session_scope() as s:
        row = s.get(AIProviderConfig, 1)
        assert row.api_key_encrypted and KEY not in row.api_key_encrypted  # ciphertext, not the key
        audit_text = " ".join(str(a.details) for a in s.scalars(select(AuditEvent)))
    assert KEY not in audit_text and "…abcd" in audit_text
    provider = get_provider(settings)  # the pipeline now uses the dashboard choice
    assert provider.name == "anthropic:claude-opus-5-5"


def test_keys_are_required_and_not_reused_across_providers(client):
    assert client.put("/api/ai/config", json={"preset": "openai", "model": "some-model"}).status_code == 422
    client.put("/api/ai/config", json={"preset": "anthropic", "api_key": KEY})
    # Switching provider without a new key must not carry the Anthropic key over to OpenAI.
    assert client.put("/api/ai/config", json={"preset": "openai", "model": "some-model"}).status_code == 422


def test_local_and_mcp_presets_need_no_key(client):
    r = client.put("/api/ai/config", json={"preset": "ollama"})
    assert r.json()["model"] == "qwen2.5-coder:7b" and r.json()["base_url"] == "http://127.0.0.1:11434/v1"
    assert get_provider(settings).name == "openai_compat:qwen2.5-coder:7b"
    client.put("/api/ai/config", json={"preset": "mcp"})
    assert get_provider(settings).name == "mcp:connected-agent"
    assert client.post("/api/ai/test").json()["ok"] is False  # no agent connected yet


def test_only_admins_change_the_provider(client):
    approver = make_user(client, "riya", "approver")
    assert client.put("/api/ai/config", json={"preset": "ollama"}, headers=approver).status_code == 403
    assert client.get("/api/ai/config", headers=approver).status_code == 200  # but can see it


def test_saving_a_key_without_master_key_fails_safely(client, monkeypatch):
    monkeypatch.setattr(settings, "secret_key", "")
    r = client.put("/api/ai/config", json={"preset": "anthropic", "api_key": KEY})
    assert r.status_code == 409 and "AION_SECRET_KEY" in r.text


def test_reset_falls_back_to_environment(client):
    client.put("/api/ai/config", json={"preset": "ollama"})
    r = client.delete("/api/ai/config")
    assert r.json()["source"] == "environment"
    assert get_provider(settings) is None  # tests run with AION_LLM_PROVIDER=none
