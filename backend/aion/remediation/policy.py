"""Patch policy: hard limits on what an AI-generated patch may touch.

These rules are enforced in code, independently of what the prompt says, so
a model that ignores its instructions still cannot (for example) delete a
failing test to make the suite pass.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

MAX_FILES_CHANGED = 5
MAX_CHANGED_LINES = 200
NEW_TEST_PATTERN = re.compile(r"^tests/test_aion_[a-z0-9_]+\.py$")
PROTECTED_PREFIXES = ("tests/", ".github/", ".gitlab-ci", "Dockerfile", ".git/", "requirements", "pyproject.toml")


class PolicyViolation(Exception):
    pass


def normalize_path(path: str) -> str:
    p = path.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    pure = PurePosixPath(p)
    if pure.is_absolute() or ".." in pure.parts or p == "" or ":" in p:
        raise PolicyViolation(f"Path {path!r} is not a safe repository-relative path")
    return str(pure)


def check_edit_path(path: str, existing_files: set[str]) -> str:
    p = normalize_path(path)
    if p.startswith(PROTECTED_PREFIXES):
        raise PolicyViolation(f"Editing {p!r} is not allowed (tests, CI and dependency files are protected)")
    if p not in existing_files:
        raise PolicyViolation(f"File {p!r} does not exist in the repository")
    return p


def check_new_file_path(path: str, existing_files: set[str]) -> str:
    p = normalize_path(path)
    if not NEW_TEST_PATTERN.match(p):
        raise PolicyViolation(f"New file {p!r} rejected: only new regression tests named tests/test_aion_*.py are allowed")
    if p in existing_files:
        raise PolicyViolation(f"New file {p!r} already exists")
    return p


def check_diff_size(diff: str) -> None:
    files = {line[6:] for line in diff.splitlines() if line.startswith("+++ b/")}
    changed = sum(1 for line in diff.splitlines()
                  if (line.startswith("+") or line.startswith("-")) and not line.startswith(("+++", "---")))
    if len(files) > MAX_FILES_CHANGED:
        raise PolicyViolation(f"Patch changes {len(files)} files (limit {MAX_FILES_CHANGED})")
    if changed > MAX_CHANGED_LINES:
        raise PolicyViolation(f"Patch changes {changed} lines (limit {MAX_CHANGED_LINES})")
