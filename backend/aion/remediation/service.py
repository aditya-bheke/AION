"""Create a candidate patch as a real commit on an isolated branch.

Every attempt gets its own git *worktree* (a second checkout of the same
repository) under workspace/worktrees/, on a branch named
`aion/incident-<id>-a<attempt>`. Production's checkout is never touched here.

Strategies:
  llm_edit - the LLM writes search/replace edits (+ a regression test).
  revert   - deterministic: `git revert` the suspected commit. Used when no LLM
             is configured. A classic, conservative remediation.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from aion import audit
from aion.ai.patcher import PatchOutput, build_patch_prompt, generate_llm_patch
from aion.ai.providers.base import LLMError, LLMProvider
from aion.ai.redact import redact_text
from aion.ai.rca import RCAOutput
from aion.config import settings
from aion.gitops.repo import GitError, GitRepo
from aion.models import Incident, PatchProposal, Service
from aion.remediation.apply import PatchApplyError, apply_edits
from aion.remediation.policy import PROTECTED_PREFIXES, PolicyViolation, check_diff_size

log = logging.getLogger("aion.remediation")
MAX_FILES_SHOWN = 4
MAX_FILE_CHARS = 20000


def worktree_path(service: Service, incident_id: int, attempt: int) -> Path:
    return settings.worktrees_dir / service.name / f"incident-{incident_id}-a{attempt}"


def _commit_message(incident: Incident, summary: str, strategy: str, generator: str, rca: RCAOutput) -> str:
    return (
        f"AION fix for incident #{incident.id}: {summary}\n\n"
        f"Strategy: {strategy} ({generator})\n"
        f"Root cause: {rca.probable_root_cause[:300]}\n"
        f"Suspected commit: {rca.suspected_commit or 'n/a'}\n\n"
        "Generated automatically by AION. Requires human approval before production deployment.\n"
    )


def _files_for_llm(repo: GitRepo, base: str, rca: RCAOutput, pack: dict[str, Any]) -> dict[str, str]:
    candidates: list[str] = list(rca.affected_files)
    for ev in pack["evidence"]:
        if ev["kind"] == "source_code":
            candidates.append(ev["file"])
    for ev in pack["evidence"]:
        if ev["kind"] == "commit" and ev["sha"] == rca.suspected_commit:
            candidates.extend(f for f in ev["files_changed"] if f.endswith(".py"))
    files: dict[str, str] = {}
    for path in candidates:
        if path in files or path.startswith(PROTECTED_PREFIXES):
            continue
        content = repo.file_at(base, path)
        if content is not None and len(content) <= MAX_FILE_CHARS:
            files[path] = content
        if len(files) >= MAX_FILES_SHOWN:
            break
    return files


def _tests_for_llm(repo: GitRepo, base: str, files: dict[str, str]) -> dict[str, str]:
    tests = [p for p in repo.ls_files(base) if p.startswith("tests/") and p.endswith(".py")]
    modules = {Path(p).stem for p in files}

    def relevance(path: str) -> int:
        text = repo.file_at(base, path) or ""
        return -sum(1 for m in modules if re.search(rf"\b{re.escape(m)}\b", text))

    chosen = sorted(tests, key=relevance)[:3]
    if "tests/conftest.py" in tests and "tests/conftest.py" not in chosen:
        chosen.append("tests/conftest.py")
    return {p: (repo.file_at(base, p) or "")[:8000] for p in chosen}


def create_patch(session: Session, incident: Incident, service: Service, rca: RCAOutput, pack: dict[str, Any],
                 failing_requests: list[dict[str, Any]], attempt: int, feedback: Optional[str],
                 provider: Optional[LLMProvider]) -> PatchProposal:
    repo = GitRepo(service.repo_path)
    base = repo.rev_parse(service.production_branch)
    branch = f"aion/incident-{incident.id}-a{attempt}"
    wt = worktree_path(service, incident.id, attempt)
    strategy = "llm_edit" if provider else "revert"
    generator = provider.name if provider else "deterministic git revert (no LLM)"

    proposal = PatchProposal(incident_id=incident.id, attempt=attempt, strategy=strategy, generator=generator,
                             branch=branch, base_sha=base, worktree_path=str(wt), status="generating")
    session.add(proposal)
    session.flush()
    # Release the SQLite write lock before the (possibly minutes-long) model call below.
    session.commit()

    if wt.exists():
        repo.remove_worktree(wt)
    repo.add_worktree(wt, branch, base)
    actor = f"ai:{provider.name}" if provider else "system:revert-generator"
    try:
        if provider:
            files = _files_for_llm(repo, base, rca, pack)
            if not files:
                raise PatchApplyError("No editable source files were identified for the fix")
            tests = _tests_for_llm(repo, base, files)
            redactions: Counter = Counter()
            if settings.redact_prompts:
                files = {p: redact_text(c, "code", redactions) for p, c in files.items()}
                tests = {p: redact_text(c, "code", redactions) for p, c in tests.items()}
                failing_requests = [{k: redact_text(v, "log", redactions) if isinstance(v, str) else v
                                     for k, v in r.items()} for r in failing_requests]
                feedback = redact_text(feedback, "log", redactions) if feedback else feedback
            prompt = build_patch_prompt(pack, rca, files, tests, failing_requests, feedback)
            result = generate_llm_patch(provider, prompt)
            out: PatchOutput = result.output
            proposal.rationale = f"{out.rationale}\n\nRisk notes: {out.risk_notes}"
            proposal.edits = [e.model_dump() for e in out.edits] + [
                {"path": nf.path, "new_file": True, "content": nf.content} for nf in out.new_test_files]
            proposal.usage = dict(result.usage, latency_ms=result.latency_ms, attempts=result.attempts,
                                  redactions=dict(redactions))
            repair_notes: list[str] = []
            apply_edits(wt, out.edits, out.new_test_files, set(repo.ls_files(base)), repair_notes)
            if repair_notes:
                proposal.rationale += "\n\nApplied by AION: " + "; ".join(repair_notes)
            summary = out.summary.strip().splitlines()[0][:120] if out.summary.strip() else "candidate fix"
        else:
            if not rca.suspected_commit:
                raise PatchApplyError("Revert strategy needs a suspected commit, but none was identified")
            try:
                repo.git("revert", "--no-commit", rca.suspected_commit, cwd=wt)
            except GitError as exc:
                repo.git("revert", "--abort", cwd=wt, check=False)
                raise PatchApplyError(f"git revert of {rca.suspected_commit[:7]} does not apply cleanly: {exc}")
            subject = (repo.git("log", "-1", "--format=%s", rca.suspected_commit) or "").strip()
            summary = f"Revert {rca.suspected_commit[:7]} \"{subject}\""
            proposal.rationale = (f"No LLM is configured, so AION proposes the conservative remediation: revert the "
                                  f"commit identified as the most likely cause ({rca.suspected_commit[:7]}). This "
                                  f"restores the behaviour that was running before it was deployed. The intended "
                                  f"feature of that commit must be re-implemented separately.")

        repo.git("add", "-A", cwd=wt)
        staged = repo.git("diff", "--cached", cwd=wt)
        check_diff_size(staged)
        proposal.commit_sha = repo.commit_all(wt, _commit_message(incident, summary, strategy, generator, rca))
        proposal.diff = repo.diff_between(base, proposal.commit_sha)
        proposal.status = "ready"
        audit.record(session, "patch_generated", actor, incident_id=incident.id, patch_id=proposal.id,
                     attempt=attempt, strategy=strategy, branch=branch, commit=proposal.commit_sha,
                     summary=summary)
    except (PatchApplyError, PolicyViolation, LLMError, GitError) as exc:
        proposal.status = "policy_rejected" if isinstance(exc, PolicyViolation) else "generation_failed"
        proposal.error = str(exc)
        repo.remove_worktree(wt)
        audit.record(session, "patch_failed", actor, incident_id=incident.id, patch_id=proposal.id,
                     attempt=attempt, error=str(exc)[:500], reason=proposal.status)
    session.flush()
    return proposal
