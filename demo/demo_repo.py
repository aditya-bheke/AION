"""Build the demo `orders-service` git repository for a scenario.

The shared base history lives in orders-service-history/ (01-initial ... 05-docs,
listed in its manifest.json). Each scenario in scenarios/<name>/scenario.json
says where the base stops (`base_until`) and which further commits to add;
each commit is a folder of files that changed ("overlay"). We copy overlays
over the working tree in order and commit them with the author and
(backdated) timestamp from the manifests, producing a realistic multi-author
history in which one commit introduces a latent bug.

The history is synthetic demo data; everything AION does with it (blame,
diffs, worktrees, merges) is real git.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
HISTORY_DIR = DEMO_DIR / "orders-service-history"
SCENARIOS_DIR = DEMO_DIR / "scenarios"
DEFAULT_SCENARIO = "expired-coupon"


@dataclass
class BuiltCommit:
    sha: str
    message: str
    authored_at: datetime
    deploy_version: str | None = None
    deployed_at: datetime | None = None


@dataclass
class Scenario:
    name: str
    title: str
    description: str
    commits: list[dict]          # base commits + scenario commits, with absolute "path"
    trigger: list[list]          # [method, path template, weight] requests that hit the bug
    expected: dict = field(default_factory=dict)


def list_scenarios() -> list[str]:
    return sorted(p.parent.name for p in SCENARIOS_DIR.glob("*/scenario.json"))


def load_scenario(name: str = DEFAULT_SCENARIO) -> Scenario:
    path = SCENARIOS_DIR / name / "scenario.json"
    if not path.exists():
        raise ValueError(f"Unknown scenario {name!r}. Available: {', '.join(list_scenarios())}")
    spec = json.loads(path.read_text(encoding="utf-8"))
    base = json.loads((HISTORY_DIR / "manifest.json").read_text(encoding="utf-8"))["commits"]
    commits = []
    for entry in base:
        # Base commits carry no deployment of their own except v1.3.0 at 05-docs.
        commits.append({**entry, "path": HISTORY_DIR / entry["dir"]})
        if entry["dir"] == spec["base_until"]:
            break
    else:
        raise ValueError(f"base_until {spec['base_until']!r} not found in the base history")
    for entry in spec["commits"]:
        commits.append({**entry, "path": (path.parent / entry["dir"]).resolve()})
    return Scenario(name=spec["name"], title=spec["title"], description=spec["description"],
                    commits=commits, trigger=spec.get("trigger", []), expected=spec.get("expected", {}))


def _git(args: list[str], cwd: Path, env: dict | None = None) -> str:
    proc = subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=str(cwd), capture_output=True, text=True,
                          env={**os.environ, **(env or {})})
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout


def build_repo(target: Path, now: datetime | None = None, scenario: str = DEFAULT_SCENARIO) -> list[BuiltCommit]:
    """Create a fresh repository at `target` for `scenario`. Any existing directory is replaced."""
    now = now or datetime.now(timezone.utc)
    spec = load_scenario(scenario)
    if target.exists():
        shutil.rmtree(target, onerror=_force_remove)
    target.mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], target)
    built: list[BuiltCommit] = []
    for entry in spec.commits:
        src: Path = entry["path"]
        for path in src.rglob("*"):
            if path.is_file():
                dst = target / path.relative_to(src)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dst)
        name, email = entry["author"].rsplit(" <", 1)
        when = now - timedelta(hours=entry["hours_ago"])
        stamp = when.strftime("%Y-%m-%dT%H:%M:%S+0000")
        env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email.rstrip(">"), "GIT_AUTHOR_DATE": stamp,
               "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email.rstrip(">"), "GIT_COMMITTER_DATE": stamp}
        _git(["add", "-A"], target)
        _git(["commit", "-q", "-m", entry["message"]], target, env)
        sha = _git(["rev-parse", "HEAD"], target).strip()
        commit = BuiltCommit(sha=sha, message=entry["message"], authored_at=when.replace(tzinfo=None))
        if entry.get("deploy"):
            commit.deploy_version = entry["deploy"]
            commit.deployed_at = (now - timedelta(hours=entry["deploy_hours_ago"])).replace(tzinfo=None)
        built.append(commit)
    return built


def _force_remove(func, path, _exc):
    # Git marks object files read-only on Windows; make them writable and retry.
    os.chmod(path, 0o700)
    func(path)
