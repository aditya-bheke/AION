"""Deterministic application of search/replace edits to a working tree."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import Optional

from aion.ai.patcher import FileEdit, NewFile
from aion.remediation.policy import PolicyViolation, check_edit_path, check_new_file_path


class PatchApplyError(Exception):
    pass


def _read(path: Path) -> str:
    # newline="" keeps \r\n intact so we write back exactly what we read.
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def _parses(source: str) -> bool:
    try:
        ast.parse(source)
        return True
    except SyntaxError:
        return False


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _reindent_variants(replace: str, base: str) -> list[tuple[str, str]]:
    """Candidate re-indentations of `replace` anchored at indentation `base`.

    Small models often drop the relative indentation of a replacement block
    (e.g. keep the first line indented but write the rest at column 0). Each
    variant is a (description, text) pair; the caller keeps the first one that
    makes the file parse again.
    """
    lines = replace.splitlines(keepends=True)
    if not lines:
        return []

    def prefix(block: list[str]) -> list[str]:
        return [(base + ln) if ln.strip() else ln for ln in block]

    variants = []
    # (a) first line re-anchored, remaining lines dedented as a block and re-anchored
    rest = textwrap.dedent("".join(lines[1:])).splitlines(keepends=True)
    variants.append(("re-indented continuation lines relative to the edited block",
                     "".join(prefix([lines[0].lstrip(" \t")] + rest))))
    # (b) whole block dedented and re-anchored
    whole = textwrap.dedent(replace).splitlines(keepends=True)
    variants.append(("re-indented the replacement block to the edited location", "".join(prefix(whole))))
    return [(d, v) for d, v in variants if v != replace]


def apply_edits(worktree: Path, edits: list[FileEdit], new_files: list[NewFile], existing_files: set[str],
                notes: Optional[list[str]] = None) -> list[str]:
    """Apply edits in memory first; write to disk only if *all* of them apply cleanly.

    For Python files, if an exact edit turns a parseable file into one that no
    longer parses, indentation-only repairs of the replacement are tried (see
    `_reindent_variants`). Any repair used is reported in `notes`; the code
    content is never altered, and validation still compiles and tests the result.
    """
    notes = notes if notes is not None else []
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
        updated = content.replace(search, replace, 1)

        if rel.endswith(".py") and _parses(content) and not _parses(updated):
            start = content.index(search)
            line_start = content.rfind("\n", 0, start) + 1
            base = _leading_ws(content[line_start:]) if not search[:1].isspace() else _leading_ws(search)
            for description, variant in _reindent_variants(replace, base):
                candidate = content.replace(search, variant, 1)
                if _parses(candidate):
                    updated = candidate
                    notes.append(f"edit[{i}] on {rel}: {description} (indentation-only repair)")
                    break
        pending[rel] = updated

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
