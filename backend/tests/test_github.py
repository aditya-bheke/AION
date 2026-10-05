"""GitHub integration without the network: a local bare repo plays GitHub's git server,
an httpx MockTransport plays the REST API (pull requests + Actions runs)."""
import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient

from aion.config import settings
from aion.integrations.github import GitHub, GitHubError, normalize_repo, set_github_factory
from aion.main import create_app
from aion.pipeline import orchestrator
from conftest import SERVICE_HEADERS, make_user
from test_end_to_end import _setup


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


class FakeGitHub:
    """Minimal GitHub REST API: pulls, pull by number, actions runs (state set by the test)."""

    def __init__(self, bare):
        self.bare = bare
        self.prs = []
        self.runs = [{"name": "CI", "event": "pull_request", "status": "in_progress", "conclusion": None,
                      "html_url": "https://github.example/run/1"}]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/pulls") and request.method == "GET":
            return httpx.Response(200, json=[])
        if path.endswith("/pulls") and request.method == "POST":
            body = __import__("json").loads(request.content)
            pr = {"number": 7, "html_url": "https://github.example/me/demo/pull/7", "head": body["head"]}
            self.prs.append(body)
            return httpx.Response(201, json=pr)
        if "/pulls/" in path:
            head = _git(self.bare, "rev-parse", self.prs[-1]["head"])
            main = _git(self.bare, "rev-parse", "main")
            merged = subprocess.run(["git", "merge-base", "--is-ancestor", head, main], cwd=str(self.bare)).returncode == 0
            return httpx.Response(200, json={"number": 7, "state": "closed" if merged else "open", "merged": merged})
        if path.endswith("/actions/runs"):
            return httpx.Response(200, json={"workflow_runs": self.runs})
        return httpx.Response(404, json={"message": "not found"})


@pytest.fixture()
def gh_env(aion_env, demo_repo, tmp_path, monkeypatch):
    monkeypatch.setattr("aion.api.incidents.enqueue_deploy", orchestrator.run_deploy)
    monkeypatch.setattr("aion.api.incidents.enqueue_rollback", orchestrator.run_rollback)
    monkeypatch.setattr(settings, "github_poll_seconds", 0)
    repo_dir, _ = demo_repo
    bare = tmp_path / "github.git"
    _git(tmp_path, "init", "--bare", "-q", "-b", "main", str(bare))
    _git(repo_dir, "push", "-q", str(bare), "main")
    fake = FakeGitHub(bare)
    set_github_factory(lambda repo: GitHub("tok-123", repo, git_url=str(bare), transport=httpx.MockTransport(fake.handler)))
    with TestClient(create_app(start_background=False)) as c:
        c.headers.update(make_user(c, "aditya", "approver"))
        yield c, fake, bare
    set_github_factory(None)


def test_normalize_repo_accepts_common_forms():
    for v in ("me/demo", "me/demo.git", "https://github.com/me/demo", "https://github.com/me/demo.git",
              "git@github.com:me/demo.git"):
        assert normalize_repo(v) == "me/demo"
    with pytest.raises(ValueError):
        normalize_repo("not a repo")


def test_pr_ci_gate_and_deploy_through_github(gh_env, demo_repo, tmp_path):
    client, fake, bare = gh_env
    repo_dir, commits, incident_id = _setup(client, demo_repo, tmp_path)
    svc = client.get("/api/services").json()[0]
    client.post("/api/services", headers=SERVICE_HEADERS,
                json={**{k: svc[k] for k in ("name", "repo_path", "test_command", "run_command")},
                      "github_repo": "https://github.com/me/demo.git"})

    orchestrator.run_pipeline(incident_id)
    d = client.get(f"/api/incidents/{incident_id}").json()
    patch = d["patches"][-1]
    assert d["incident"]["status"] == "awaiting_approval"
    assert d["pull_request"]["number"] == 7 and d["pull_request"]["ci_state"] == "pending"
    assert _git(bare, "rev-parse", patch["branch"]) == patch["commit_sha"]       # branch pushed
    assert fake.prs[0]["base"] == "main" and "Do not merge manually" in fake.prs[0]["body"]

    r = client.post(f"/api/incidents/{incident_id}/approve", json={})
    assert r.status_code == 409 and "GitHub Actions" in r.text                     # CI gate

    fake.runs[0].update(status="completed", conclusion="success")
    assert client.get(f"/api/incidents/{incident_id}").json()["pull_request"]["ci_state"] == "success"
    assert client.post(f"/api/incidents/{incident_id}/approve", json={}).status_code == 200
    assert client.post(f"/api/incidents/{incident_id}/deploy").status_code == 200

    d = client.get(f"/api/incidents/{incident_id}").json()
    assert d["incident"]["status"] == "resolved"
    assert _git(bare, "rev-parse", "main") == patch["commit_sha"]                  # same artefact on GitHub
    assert d["pull_request"]["state"] == "merged"
    actions = {a["action"] for a in d["audit"]}
    assert {"github_pr_opened", "github_ci_completed"} <= actions

    client.post(f"/api/incidents/{incident_id}/rollback", json={"comment": "test"})
    assert _git(bare, "rev-parse", "main") == _git(repo_dir, "rev-parse", "main")  # revert pushed too


def test_failed_ci_blocks_approval(gh_env, demo_repo, tmp_path):
    client, fake, bare = gh_env
    repo_dir, commits, incident_id = _setup(client, demo_repo, tmp_path)
    svc = client.get("/api/services").json()[0]
    client.post("/api/services", headers=SERVICE_HEADERS,
                json={**{k: svc[k] for k in ("name", "repo_path", "test_command", "run_command")}, "github_repo": "me/demo"})
    fake.runs[0].update(status="completed", conclusion="failure")
    orchestrator.run_pipeline(incident_id)
    assert client.get(f"/api/incidents/{incident_id}").json()["pull_request"]["ci_state"] == "failure"
    r = client.post(f"/api/incidents/{incident_id}/approve", json={})
    assert r.status_code == 409 and "failure" in r.text


def test_errors_never_leak_the_token(tmp_path):
    gh = GitHub("secret-token-xyz", "me/demo", git_url=str(tmp_path / "missing.git"),
                transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad credentials secret-token-xyz")))
    with pytest.raises(GitHubError) as e1:
        gh.api("GET", "/repos/me/demo")
    _git(tmp_path, "init", "-q")
    with pytest.raises(GitHubError) as e2:
        gh.push(tmp_path, "HEAD:refs/heads/main")
    assert "secret-token-xyz" not in str(e1.value) + str(e2.value)
