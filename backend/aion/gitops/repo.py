"""Thin wrapper around the `git` command-line tool.

We call the real git binary through `subprocess` (no shell) instead of using
a Git library. The commands are exactly the ones an engineer would type, which
keeps the behaviour transparent and easy to explain/debug.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

AION_AUTHOR_NAME = "AION Bot"
AION_AUTHOR_EMAIL = "aion-bot@localhost"


class GitError(RuntimeError):
    pass


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int


@dataclass
class Commit:
    sha: str
    author: str
    email: str
    authored_at: datetime
    message: str
    files: list[str] = field(default_factory=list)


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class GitRepo:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    # -- plumbing -----------------------------------------------------------
    def git(self, *args: str, cwd: Optional[Path] = None, check: bool = True, timeout: int = 60) -> str:
        cmd = ["git", "-c", f"user.name={AION_AUTHOR_NAME}", "-c", f"user.email={AION_AUTHOR_EMAIL}",
               "-c", "core.autocrlf=false", *args]
        proc = subprocess.run(cmd, cwd=str(cwd or self.path), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout

    def is_repo(self) -> bool:
        try:
            return self.git("rev-parse", "--is-inside-work-tree").strip() == "true"
        except (GitError, FileNotFoundError, NotADirectoryError):
            return False

    def rev_parse(self, rev: str) -> str:
        return self.git("rev-parse", rev).strip()

    def has_commit(self, sha: str) -> bool:
        proc = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=str(self.path), capture_output=True)
        return proc.returncode == 0

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        proc = subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, descendant],
                              cwd=str(self.path), capture_output=True)
        return proc.returncode == 0

    # -- history ------------------------------------------------------------
    def commits(self, rev_range: str, max_count: int = 50) -> list[Commit]:
        """Commits in `rev_range` (e.g. 'abc..def' or 'main'), newest first, with changed files."""
        sep, end = "\x1f", "\x1e"
        out = self.git("log", f"--max-count={max_count}", "--name-only",
                       f"--format={end}%H{sep}%an{sep}%ae{sep}%at{sep}%B{sep}", rev_range)
        result = []
        for block in out.split(end):
            if not block.strip():
                continue
            sha, author, email, ts, rest = block.split(sep, 4)
            # rest = "<message body>" + sep + "\n" + file list
            message, _, files_part = rest.partition(sep) if sep in rest else (rest, "", "")
            files = [f.strip() for f in files_part.splitlines() if f.strip()]
            result.append(Commit(
                sha=sha.strip(), author=author, email=email,
                authored_at=datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(tzinfo=None),
                message=message.strip(), files=files,
            ))
        return result

    def diff_for_commit(self, sha: str, context: int = 3, max_chars: int = 12000) -> str:
        out = self.git("show", "--format=", f"-U{context}", sha)
        return out if len(out) <= max_chars else out[:max_chars] + "\n... [diff truncated]\n"

    def changed_hunks(self, sha: str) -> dict[str, list[Hunk]]:
        """Line ranges changed by a commit, per file (zero-context diff)."""
        out = self.git("show", "--format=", "-U0", sha)
        hunks: dict[str, list[Hunk]] = {}
        current: Optional[str] = None
        for line in out.splitlines():
            if line.startswith("+++ "):
                target = line[4:].strip()
                current = None if target == "/dev/null" else target.removeprefix("b/")
            elif current and line.startswith("@@"):
                m = _HUNK_RE.match(line)
                if m:
                    hunks.setdefault(current, []).append(Hunk(
                        int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1)))
        return hunks

    def file_at(self, rev: str, path: str) -> Optional[str]:
        try:
            return self.git("show", f"{rev}:{path}")
        except GitError:
            return None

    def ls_files(self, rev: str = "HEAD") -> list[str]:
        return [p for p in self.git("ls-tree", "-r", "--name-only", rev).splitlines() if p]

    # -- worktrees / branches -------------------------------------------------
    def add_worktree(self, path: Path, branch: str, base: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.git("worktree", "add", "-B", branch, str(path), base)

    def remove_worktree(self, path: Path) -> None:
        self.git("worktree", "remove", "--force", str(path), check=False)
        self.git("worktree", "prune", check=False)

    def commit_all(self, cwd: Path, message: str) -> str:
        self.git("add", "-A", cwd=cwd)
        self.git("commit", "-m", message, cwd=cwd)
        return self.git("rev-parse", "HEAD", cwd=cwd).strip()

    def diff_between(self, base: str, head: str) -> str:
        return self.git("diff", base, head)

    def current_branch(self) -> str:
        return self.git("rev-parse", "--abbrev-ref", "HEAD").strip()

    def merge_ff_only(self, branch: str) -> None:
        self.git("merge", "--ff-only", branch)
