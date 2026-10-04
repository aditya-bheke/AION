"""Deterministic application of search/replace edits to a working tree."""
from __future__ import annotations

from pathlib import Path

from aion.ai.patcher import FileEdit, NewFile
from aion.remediation.policy import PolicyViolation, check_edit_path, check_new_file_path


class PatchApplyError(Exception):
    pass


def _read(path: Path) -> str:
    # newline="" keeps \r\n intact so we write back exactly what we read.
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def apply_edits(worktree: Path, edits: list[FileEdit], new_files: list[NewFile], existing_files: set[str]) -> list[str]:
    """Apply edits in memory first; write to disk only if *all* of them apply cleanly."""
    pending: dict[str, str] = {}
    for i, edit in enumerate(edits):
        try:
            rel = check_edit_path(edit.path, existing_files)
        except PolicyViolation:
            raise
        content = pending.get(rel) if rel in pending else _read(worktree / rel)
        search = edit.search
        uses_crlf = "\r\n" in content
        if uses_crlf:
            search = search.replace("\r\n", "\n").replace("\n", "\r\n")
        if not search.strip():
            raise PatchApplyError(f"edit[{i}] on {rel}: empty search text")
        occurrences = content.count(search)
        if occurrences == 0:
            raise PatchApplyError(f"edit[{i}] on {rel}: search text not found in the file "
                                  f"(first line: {edit.search.strip().splitlines()[0][:80]!r})")
        if occurrences > 1:
            raise PatchApplyError(f"edit[{i}] on {rel}: search text is ambiguous ({occurrences} matches)")
        replace = edit.replace.replace("\r\n", "\n").replace("\n", "\r\n") if uses_crlf else edit.replace
        pending[rel] = content.replace(search, replace, 1)

    created: dict[str, str] = {}
    for nf in new_files:
        rel = check_new_file_path(nf.path, existing_files)
        created[rel] = nf.content if nf.content.endswith("\n") else nf.content + "\n"

    if not pending and not created:
        raise PatchApplyError("The patch contains no changes")
    for rel, text in {**pending, **created}.items():
        target = worktree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    return sorted(pending) + sorted(created)
