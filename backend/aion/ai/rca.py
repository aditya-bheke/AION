"""Root-cause analysis: LLM reasoning over the evidence pack, then grounding checks.

Two analyzers produce the same `RCAOutput` structure:

* LLM analyzer        - the configured model reasons over the rendered evidence.
* Heuristic analyzer  - deterministic, no LLM: reports the top-ranked suspect
                        from the correlation engine. Used when no model is
                        configured, and clearly labelled as such.

Whatever the analyzer, `ground()` then checks every claim against the pack.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel, Field

from aion.ai.context import render_evidence
from aion.ai.providers.base import LLMProvider, generate_structured


class ObservedEvidence(BaseModel):
    evidence_id: str = Field(description="ID of the evidence item, e.g. LOG-1, TRACE-1, COMMIT-abc1234")
    observation: str = Field(description="A fact directly visible in that evidence item (no interpretation)")


class Inference(BaseModel):
    statement: str = Field(description="A conclusion drawn from the evidence")
    based_on: list[str] = Field(description="Evidence IDs this conclusion relies on")


class RCAOutput(BaseModel):
    probable_root_cause: str = Field(description="One or two sentences: the most likely root cause")
    observed_evidence: list[ObservedEvidence]
    inferences: list[Inference]
    affected_service: str
    affected_files: list[str] = Field(description="Repository-relative paths of files that need to change")
    suspected_commit: str = Field(description="Full or short SHA of the commit that introduced the problem, "
                                              "chosen from the COMMIT evidence; empty string if none")
    confidence: float = Field(description="0.0 - 1.0")
    confidence_rationale: str
    remediation: str = Field(description="Concrete recommended fix")
    alternative_hypotheses: list[str]


RCA_SYSTEM_PROMPT = """You are AION's root-cause analysis engine, assisting on-call engineers during a production incident.

You receive an evidence pack: deduplicated log clusters, a stack trace, deployments, suspect commits with diffs and correlation scores, source code of the failing functions, and similar past incidents. Each item has an ID such as LOG-1, TRACE-1, DEPLOY-1, COMMIT-abc1234, CODE-1, INC-7.

Rules:
1. Separate OBSERVATIONS from INFERENCES. `observed_evidence` holds only facts directly readable in an evidence item, each with that item's ID. `inferences` holds your reasoning, each listing the evidence IDs it depends on.
2. Cite only IDs that appear in the pack. Never invent files, functions, commits or log lines.
3. `suspected_commit` must be one of the COMMIT items (or an empty string if none is plausible). Correlation scores are heuristics: confirm them by reading the diffs and code, and disagree when the code says otherwise.
4. Log clusters marked pre_existing are probably background noise; do not attribute the incident to them without a reason.
5. `affected_files` lists the repository-relative files that must change to fix the problem.
6. Calibrate `confidence`: high (>0.8) only when the diff, stack trace and timing all point to the same change. Explain the calibration in `confidence_rationale`.
7. `remediation` describes a specific code-level fix, not generic advice."""


def rca_user_prompt(pack: dict[str, Any]) -> str:
    return (
        render_evidence(pack)
        + "\n\n# TASK\nDetermine the probable root cause of this incident and recommend a remediation. "
        "Return the structured JSON result."
    )


@dataclass
class RCAResult:
    output: RCAOutput
    analyzer: str
    raw_text: Optional[str]
    usage: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def run_llm_rca(provider: LLMProvider, pack: dict[str, Any]) -> RCAResult:
    result = generate_structured(provider, RCA_SYSTEM_PROMPT, rca_user_prompt(pack), RCAOutput)
    usage = dict(result.usage, latency_ms=result.latency_ms, attempts=result.attempts)
    return RCAResult(result.output, provider.name, result.raw_text, usage)


def run_heuristic_rca(pack: dict[str, Any]) -> RCAResult:
    """Deterministic fallback: summarise what the correlation engine found. No language model involved."""
    ev = {e["id"]: e for e in pack["evidence"]}
    trace = ev.get("TRACE-1")
    commits = [e for e in pack["evidence"] if e["kind"] == "commit"]
    deploy = ev.get("DEPLOY-1")
    incident_log = next((e for e in pack["evidence"] if e.get("classification") == "incident_signature"), None)
    top = commits[0] if commits else None

    frame_txt = trace["repo_frames"][-1] if trace and trace["repo_frames"] else "an unknown location"
    exc_txt = trace["exception"] if trace else pack["incident"]["title"]
    observed: list[ObservedEvidence] = []
    inferences: list[Inference] = []
    if incident_log:
        observed.append(ObservedEvidence(evidence_id=incident_log["id"], observation=(
            f"{incident_log['count_in_window']} occurrences of '{incident_log['template'][:120]}' "
            f"between {incident_log['first_seen']} and {incident_log['last_seen']}; first ever seen "
            f"{incident_log['first_ever_seen']}.")))
    if trace:
        observed.append(ObservedEvidence(evidence_id="TRACE-1",
                                         observation=f"{exc_txt} raised at {frame_txt}."))
    if deploy:
        observed.append(ObservedEvidence(evidence_id=deploy["id"], observation=(
            f"Deployment {deploy['version']} (commit {deploy['commit']}) went live at {deploy['deployed_at']} UTC.")))
    if top:
        observed.append(ObservedEvidence(evidence_id=top["id"], observation="; ".join(top["correlation_reasons"])))
        inferences.append(Inference(
            statement=(f"Commit {top['sha'][:7]} (\"{top['message'].splitlines()[0]}\") most likely introduced the "
                       f"failure: it ranks highest on blame, file-overlap and deployment-timing signals."),
            based_on=[i for i in [top["id"], "TRACE-1", deploy["id"] if deploy else None] if i]))
    files = sorted({f.split(":")[0] for f in (trace["repo_frames"] if trace else [])}
                   .intersection(top["files_changed"] if top else []))
    if not files and top:
        files = top["files_changed"]
    score = float(top["correlation_score"]) if top else 0.0
    root = (f"{exc_txt} at {frame_txt}. The failing code was most recently changed by commit "
            f"{top['sha'][:7]} \"{top['message'].splitlines()[0]}\" by {top['author']}"
            + (f", shipped in deployment {deploy['version']}" if deploy else "") + "."
            ) if top else f"{exc_txt} at {frame_txt}. No recent commit could be correlated with the failure."
    output = RCAOutput(
        probable_root_cause=root,
        observed_evidence=observed,
        inferences=inferences,
        affected_service=pack["incident"]["service"],
        affected_files=files,
        suspected_commit=top["sha"] if top else "",
        confidence=round(min(score, 1.0) * 0.8, 2),  # heuristic ranking is not semantic understanding
        confidence_rationale=("Deterministic correlation score of the top suspect, discounted by 20% because no "
                              "semantic analysis of the code was performed (no LLM configured)."),
        remediation=(f"Revert commit {top['sha'][:7]} to restore the previous behaviour, then re-implement the "
                     f"change with handling for the failing case." if top else
                     "Investigate manually: no correlated change was found."),
        alternative_hypotheses=[f"{c['id']} (score {c['correlation_score']})" for c in commits[1:3]],
    )
    return RCAResult(output, "heuristic (no LLM)", None, {})


def ground(result: RCAResult, pack: dict[str, Any], repo_files: set[str]) -> RCAResult:
    """Verify AI claims against the evidence pack and the repository.

    Unverifiable claims are removed or flagged, and confidence is capped when
    the model cited things that do not exist - a guard against hallucination.
    """
    out = result.output
    ids = {e["id"] for e in pack["evidence"]}
    commits = [e["sha"] for e in pack["evidence"] if e["kind"] == "commit"]
    warnings = list(result.warnings)

    kept = []
    for item in out.observed_evidence:
        if item.evidence_id in ids:
            kept.append(item)
        else:
            warnings.append(f"Removed observation citing unknown evidence ID {item.evidence_id!r}.")
    out.observed_evidence = kept
    for inf in out.inferences:
        unknown = [i for i in inf.based_on if i not in ids]
        if unknown:
            warnings.append(f"Inference cites unknown evidence {unknown}: \"{inf.statement[:80]}\"")
            inf.based_on = [i for i in inf.based_on if i in ids]
        if not inf.based_on:
            warnings.append(f"Inference has no supporting evidence: \"{inf.statement[:80]}\"")

    valid_files = []
    for f in out.affected_files:
        norm = f.replace("\\", "/").strip()
        while norm.startswith("./"):
            norm = norm[2:]
        if norm in repo_files:
            valid_files.append(norm)
        else:
            warnings.append(f"Removed affected file not present in the repository: {f!r}.")
    out.affected_files = valid_files

    if out.suspected_commit:
        match = [c for c in commits if c.startswith(out.suspected_commit.strip().lower())]
        if len(match) == 1:
            out.suspected_commit = match[0]
        else:
            warnings.append(f"Suspected commit {out.suspected_commit!r} is not one of the candidate commits; cleared.")
            out.suspected_commit = ""
    if commits and out.suspected_commit and out.suspected_commit != commits[0]:
        warnings.append("Note: the analyzer's suspected commit differs from the top-ranked correlation suspect "
                        f"({commits[0][:7]}). Review both.")

    out.confidence = max(0.0, min(1.0, float(out.confidence)))
    hard_failures = [w for w in warnings if not w.startswith("Note:")]
    if hard_failures and out.confidence > 0.6:
        out.confidence = 0.6
        warnings.append("Confidence capped at 0.60 because some claims could not be verified.")
    if not out.observed_evidence:
        out.confidence = min(out.confidence, 0.3)
        warnings.append("No verifiable observations were cited; confidence capped at 0.30.")
    result.warnings = warnings
    return result
