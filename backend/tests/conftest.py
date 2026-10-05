import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

os.environ.setdefault("AION_ENABLE_BACKGROUND", "false")
os.environ["AION_LLM_PROVIDER"] = "none"

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "demo"))

from aion.ai.providers.factory import set_provider_override  # noqa: E402
from aion.config import settings  # noqa: E402
from aion.db import init_engine, session_scope  # noqa: E402
from aion.security import create_user, reset_login_throttle  # noqa: E402
from demo_repo import build_repo  # noqa: E402


SERVICE_TOKEN = "test-service-token-0123456789"
AGENT_TOKEN = "test-agent-token-0123456789"
TEST_SECRET_KEY = "kq4Qe0B6v5Zc3xT1mJ8yR2wN7pL9aS0dF4gH6jK8lM0="  # a valid Fernet key, tests only
AGENT_HEADERS = {"Authorization": f"Bearer {AGENT_TOKEN}"}


@pytest.fixture()
def aion_env(tmp_path, monkeypatch):
    """Fresh database + workspace per test."""
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{(tmp_path / 'aion.db').as_posix()}")
    monkeypatch.setattr(settings, "auto_pipeline", False)
    monkeypatch.setattr(settings, "service_token", SERVICE_TOKEN)
    monkeypatch.setattr(settings, "agent_token", AGENT_TOKEN)
    # Never let tests reach the real GitHub repo/token from backend/.env.
    monkeypatch.setattr(settings, "github_token", "")
    monkeypatch.setattr(settings, "github_repo", "")
    monkeypatch.setattr(settings, "secret_key", TEST_SECRET_KEY)
    monkeypatch.setattr(settings, "password_iterations", 1000)  # fast hashing in tests only
    monkeypatch.setattr(settings, "required_approvals", 1)
    settings.worktrees_dir.mkdir(parents=True, exist_ok=True)
    init_engine(settings.database_url)
    set_provider_override(None)
    reset_login_throttle()
    yield tmp_path
    set_provider_override(None)


def make_user(client, username: str, role: str, password: str = "correct horse battery") -> dict:
    """Create a user directly in the DB, sign in through the API, return auth headers."""
    with session_scope() as s:
        create_user(s, username, password, role)
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


SERVICE_HEADERS = {"Authorization": f"Bearer {SERVICE_TOKEN}"}


@pytest.fixture()
def demo_repo(tmp_path):
    repo = tmp_path / "orders-service"
    commits = build_repo(repo)
    return repo, commits


def generate_service_logs(repo: Path, log_file: Path, broken_requests: int = 8) -> list[dict]:
    """Run the real demo service in a subprocess and return its JSON log lines."""
    script = textwrap.dedent(f"""
        import os
        os.environ["SERVICE_LOG_FILE"] = {str(log_file)!r}
        from fastapi.testclient import TestClient
        from app.main import app
        c = TestClient(app, raise_server_exceptions=False)
        for i in range(3):
            c.get("/products"); c.get("/orders/1001"); c.get("/orders/1002/total?coupon=WELCOME10")
            c.post("/orders/1003/pay")
        for i in range({broken_requests}):
            c.get(f"/orders/{{1001 + i % 8}}/total?coupon=SUMMER23")
    """)
    subprocess.run([sys.executable, "-c", script], cwd=str(repo), check=True, capture_output=True)
    return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
