"""Candidate patch generation by the LLM.

The model returns *search/replace edits* rather than a unified diff: each edit
quotes an exact snippet of the current file and its replacement. Models are
much more reliable at quoting code than at producing correct diff hunk
headers, and the edit can be applied (or rejected) deterministically.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from aion.ai.providers.base import LLMProvider, StructuredResult, generate_structured
from aion.ai.rca import RCAOutput


class FileEdit(BaseModel):
    path: str = Field(description="Repository-relative path of an existing file")
    search: str = Field(description="Exact, contiguous text copied from the current file (include enough lines "
                                    "to be unique). Must match character-for-character, including indentation.")
    replace: str = Field(description="Text that replaces `search`")


class NewFile(BaseModel):
    path: str = Field(description="New test file path, must match tests/test_aion_*.py")
    content: str


class PatchOutput(BaseModel):
    summary: str = Field(description="One-line description of the fix (used as commit subject)")
    rationale: str = Field(description="Why this change fixes the root cause")
    edits: list[FileEdit]
    new_test_files: list[NewFile] = Field(description="Optional regression test(s) that fail before the fix and "
                                                      "pass after it")
    risk_notes: str


PATCH_SYSTEM_PROMPT = """You are AION's remediation engine. You write minimal, safe code fixes for production incidents. A human engineer reviews every patch, and automated tests plus a staging replay validate it before anyone can approve it.

Rules:
1. Fix the root cause with the smallest correct change. Do not refactor, rename, or reformat unrelated code.
2. Express changes as search/replace edits. `search` must be copied EXACTLY from the file contents shown (same indentation and spacing) and must appear exactly once in that file. `replace` must contain complete lines with the exact indentation they must have in the file (Python indentation is syntax).
2b. Handle the failing value everywhere it is used in the affected function, not only on the line that crashed.
3. You may only edit the files shown to you. Do not modify existing tests or CI configuration; never weaken or delete assertions to make tests pass.
4. Add one regression test as a new file named tests/test_aion_<short_name>.py that reproduces the incident (it must fail on the current code and pass with your fix). Use the same test style and imports as the existing tests shown.
5. Preserve existing behaviour for inputs that currently work.
6. Choose a sensible behaviour for the failing input (e.g. a clear 4xx client error or a safe default) and explain it in `rationale`."""


def build_patch_prompt(pack: dict[str, Any], rca: RCAOutput, files: dict[str, str], tests: dict[str, str],
                       failing_requests: list[dict[str, Any]], feedback: Optional[str]) -> str:
    parts = [
        "# ROOT CAUSE ANALYSIS",
        f"Probable root cause: {rca.probable_root_cause}",
        f"Suspected commit: {rca.suspected_commit or '(none)'}",
        f"Recommended remediation: {rca.remediation}",
        "Key inferences:",
        *[f"- {i.statement}" for i in rca.inferences],
        "",
        "# FAILING REQUESTS OBSERVED IN PRODUCTION",
        *[f"- {r['method']} {r['path']}{'?' + r['query'] if r.get('query') else ''} -> {r.get('status')}"
          for r in failing_requests[:8]],
        "",
        "# STACK TRACE",
        next((e["stack_trace"] for e in pack["evidence"] if e["id"] == "TRACE-1"), "(not available)"),
    ]
    commit_ev = next((e for e in pack["evidence"] if e["kind"] == "commit" and e["sha"] == rca.suspected_commit), None)
    if commit_ev:
        parts += ["", f"# DIFF OF SUSPECTED COMMIT {commit_ev['sha'][:7]}: {commit_ev['message'].splitlines()[0]}",
                  commit_ev["diff"]]
    parts += ["", "# CURRENT CONTENTS OF FILES YOU MAY EDIT"]
    for path, content in files.items():
        parts += [f"\n## {path}", "```python", content.rstrip(), "```"]
    if tests:
        parts += ["", "# EXISTING TESTS (read-only, for style and fixtures)"]
        for path, content in tests.items():
            parts += [f"\n## {path}", "```python", content.rstrip(), "```"]
    if feedback:
        parts += ["", "# YOUR PREVIOUS ATTEMPT FAILED", feedback,
                  "Produce a corrected patch that addresses this failure."]
    parts += ["", "# TASK", "Write the fix as search/replace edits plus a regression test. Return the JSON result."]
    return "\n".join(parts)


def generate_llm_patch(provider: LLMProvider, prompt: str) -> StructuredResult:
    return generate_structured(provider, PATCH_SYSTEM_PROMPT, prompt, PatchOutput)
