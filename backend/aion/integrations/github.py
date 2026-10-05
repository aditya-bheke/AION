"""GitHub integration: pull requests for validated fixes, GitHub Actions as an extra CI gate.

Flow (when a service is linked to a GitHub repository and AION_GITHUB_TOKEN is set):
  1. Local validation passes  -> push branch `aion/incident-<id>-a<n>` and open a pull request
     whose description carries the root cause, the validation results and the rule that it is
     deployed only through AION after human approval.
  2. GitHub Actions runs the repository's own CI on the PR; AION reads the workflow runs for
     the PR's head commit (Actions API) and shows them. Approval and deployment are blocked
     until they succeed (AION_REQUIRE_GITHUB_CI).
  3. Deploy (human)            -> fast-forward GitHub `main` to the validated commit with a
     normal (non-force) push, then the local production branch. GitHub marks the PR merged
     because its head commit is now on `main`. Same artefact everywhere - no merge commit.
  4. Rollback                  -> the revert commit is pushed to GitHub `main` too.

Authentication: a fine-grained personal access token limited to the one repository
(Contents, Pull requests, Workflows: read/write; Actions: read). Git pushes send it as an
HTTP header for that single command - it is never written into the repository's config.
"""
from __future__ import annotations

import base64
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from aion.config import settings

API = "https://api.github.com"
_REPO = re.compile(r"^(?:https?://github\.com/|git@github\.com:)?([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


class GitHubError(RuntimeError):
    pass


def normalize_repo(value: str) -> str:
    """Accept owner/name, owner/name.git or a github.com URL; return owner/name."""
    m = _REPO.match((value or "").strip())
    if not m:
        raise ValueError(f"Not a GitHub repository: {value!r} (expected owner/name)")
    return f"{m.group(1)}/{m.group(2)}"


@dataclass
class CIStatus:
    state: str                 # "none" | "pending" | "success" | "failure"
    runs: list[dict[str, Any]]


class GitHub:
    def __init__(self, token: str, repo: str, api_url: str = API, git_url: Optional[str] = None,
                 transport: Optional[httpx.BaseTransport] = None):
        self.token = token
        self.repo = normalize_repo(repo)
        self.api_url = api_url.rstrip("/")
        self.git_url = git_url or f"https://github.com/{self.repo}.git"
        self._transport = transport

    # -- helpers --------------------------------------------------------------------------
    def _redact(self, text: str) -> str:
        return text.replace(self.token, "***") if self.token else text

    def api(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        try:
            with httpx.Client(base_url=self.api_url, headers=headers, timeout=30, transport=self._transport) as c:
                r = c.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise GitHubError(self._redact(f"GitHub API unreachable: {exc}")) from exc
        if r.status_code >= 400:
            raise GitHubError(self._redact(f"GitHub API {method} {path} -> {r.status_code}: {r.text[:300]}"))
        return r.json() if r.content else None

    def push(self, repo_dir: Path, refspec: str, force: bool = False) -> None:
        """git push <github> <refspec>, authenticated for this one command only."""
        auth = base64.b64encode(f"x-access-token:{self.token}".encode()).decode()
        cmd = ["git", "-c", f"http.extraHeader=Authorization: Basic {auth}", "push", "--porcelain"]
        cmd += ["--force"] if force else []
        cmd += [self.git_url, refspec]
        proc = subprocess.run(cmd, cwd=str(repo_dir), capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise GitHubError(self._redact(f"git push {refspec} failed: {(proc.stderr or proc.stdout).strip()[-500:]}"))

    # -- pull requests & CI -------------------------------------------------------------------
    def open_pull_request(self, branch: str, base: str, title: str, body: str) -> dict[str, Any]:
        existing = self.api("GET", f"/repos/{self.repo}/pulls",
                            params={"head": f"{self.repo.split('/')[0]}:{branch}", "state": "open"})
        if existing:
            return existing[0]
        return self.api("POST", f"/repos/{self.repo}/pulls",
                        json={"title": title, "head": branch, "base": base, "body": body})

    def pull_request(self, number: int) -> dict[str, Any]:
        return self.api("GET", f"/repos/{self.repo}/pulls/{number}")

    def ci_status(self, head_sha: str) -> CIStatus:
        """Aggregate the GitHub Actions workflow runs for a commit."""
        data = self.api("GET", f"/repos/{self.repo}/actions/runs", params={"head_sha": head_sha, "per_page": 20})
        runs = [{"name": r.get("name"), "event": r.get("event"), "status": r.get("status"),
                 "conclusion": r.get("conclusion"), "url": r.get("html_url")}
                for r in (data or {}).get("workflow_runs", [])]
        if not runs:
            return CIStatus("none", runs)
        if any(r["status"] != "completed" for r in runs):
            return CIStatus("pending", runs)
        ok = all(r["conclusion"] in ("success", "skipped", "neutral") for r in runs)
        return CIStatus("success" if ok else "failure", runs)


# ---- which services use GitHub ------------------------------------------------------------
_factory_override: Optional[Callable[[str], GitHub]] = None


def set_github_factory(factory: Optional[Callable[[str], GitHub]]) -> None:
    """Tests inject a GitHub client backed by a local bare repo + mocked API."""
    global _factory_override
    _factory_override = factory


def github_for(service) -> Optional[GitHub]:
    """The GitHub client for a service, or None if the service is not linked / no token is set."""
    from aion.db import session_scope
    from aion.models import ServiceGitHub
    from sqlalchemy import select

    with session_scope() as s:
        link = s.scalar(select(ServiceGitHub).where(ServiceGitHub.service_id == service.id))
        repo = link.repo if link else None
    if not repo:
        return None
    if _factory_override is not None:
        return _factory_override(repo)
    if not settings.github_token:
        return None
    return GitHub(settings.github_token, repo)
