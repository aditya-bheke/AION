"""Build the demo `orders-service` git repository from the history overlays.

Each folder in orders-service-history/ (01-initial, 02-pricing, ...) contains
the files that changed in that commit. We copy them over the working tree in
order and commit each one with the author and (backdated) timestamp from
manifest.json, producing a realistic multi-author history in which commit 06
introduces a latent bug that the existing tests do not catch.

The history is synthetic demo data; everything AION does with it (blame,
diffs, worktrees, merges) is real git.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

HISTORY_DIR = Path(__file__).resolve().parent / "orders-service-history"


@dataclass
class BuiltCommit:
    sha: str
    message: str
    authored_at: datetime
    deploy_version: str | None = None
    deployed_at: datetime | None = None


def _git(args: list[str], cwd: Path, env: dict | None = None) -> str:
    proc = subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=str(cwd), capture_output=True, text=True,
                          env={**os.environ, **(env or {})})
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout


def build_repo(target: Path, now: datetime | None = None, history_dir: Path = HISTORY_DIR) -> list[BuiltCommit]:
    """Create a fresh repository at `target`. Any existing directory is replaced."""
    now = now or datetime.now(timezone.utc)
    if target.exists():
        shutil.rmtree(target, onerror=_force_remove)
    target.mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], target)
    manifest = json.loads((history_dir / "manifest.json").read_text(encoding="utf-8"))
    built: list[BuiltCommit] = []
    for entry in manifest["commits"]:
        src = history_dir / entry["dir"]
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
