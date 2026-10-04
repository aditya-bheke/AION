"""Evidence pack: the curated, bounded context given to the AI.

Instead of dumping raw logs into a prompt, AION assembles a small set of
*evidence items*, each with a stable ID the model must cite:

    LOG-n      deduplicated log clusters around the incident (with counts and
               a classification: incident / new / pre-existing noise)
    TRACE-1    a representative stack trace + sample failing requests
    DEPLOY-n   deployments before the incident
    COMMIT-x   top suspect commits: scores, reasons and their diffs
    CODE-n     source of the functions in the stack trace, at the deployed revision
    INC-n      similar past incidents and how they were fixed (retrieval)

The same pack is stored with the RCA report so a reviewer can see exactly
what the AI was shown.
"""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aion.gitops.correlation import CorrelationResult
from aion.gitops.repo import GitRepo
from aion.logs.normalize import is_library_frame
from aion.models import Incident, LogEvent, LogSignature, PatchProposal, RCAReport, Service

CONTEXT_WINDOW_BEFORE = timedelta(minutes=15)
MAX_CLUSTERS = 8
MAX_COMMITS = 4
MAX_SNIPPET_LINES = 60
_WORD = re.compile(r"[a-z_][a-z0-9_]{2,}")


def _numbered(source: str, start: int, end: int) -> str:
    lines = source.splitlines()
    start = max(start, 1)
    end = min(end, len(lines))
    return "\n".join(f"{i:4d} | {lines[i - 1]}" for i in range(start, end + 1))


_FRAME_LINE = re.compile(r'^\s*File "(?P<file>[^"]+)", line \d+, in ')


def compact_stack_trace(trace: str) -> str:
    """Keep application frames (with their code line); collapse framework frames.

    A typical web-framework traceback is ~90% library frames that carry no
    information about *our* bug. Collapsing them saves tokens and attention.
    """
    lines = (trace or "").rstrip().splitlines()
    out: list[str] = []
    skipped = 0
    i = 0
    while i < len(lines):
        m = _FRAME_LINE.match(lines[i])
        if m:
            has_code = i + 1 < len(lines) and not _FRAME_LINE.match(lines[i + 1]) and lines[i + 1].startswith("    ")
            block = lines[i : i + (2 if has_code else 1)]
            i += len(block)
            if is_library_frame(m.group("file")):
                skipped += 1
                continue
            if skipped:
                out.append(f"  ... {skipped} framework/library frame(s) omitted ...")
                skipped = 0
            out.extend(block)
        else:
            if skipped:
                out.append(f"  ... {skipped} framework/library frame(s) omitted ...")
                skipped = 0
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def _tokens(*texts: Optional[str]) -> set[str]:
    out: set[str] = set()
    for t in texts:
        out.update(_WORD.findall((t or "").lower()))
    return out


def similar_incidents(session: Session, incident: Incident, limit: int = 2) -> list[tuple[Incident, float]]:
    """Lexical retrieval over past, finished incidents (Jaccard similarity of tokens).

    The incident history is small and highly structured (signatures, exception
    types, function names), so exact-signature match + token overlap is both
    effective and explainable. A vector index is a planned upgrade once the
    history is large and phrased more variably (see DECISIONS.md).
    """
    query_tokens = _tokens(incident.title)
    sample = session.scalar(select(LogEvent).where(LogEvent.signature == incident.signature).limit(1))
    if sample:
        query_tokens |= _tokens(sample.template, " ".join(f["function"] for f in sample.frames or []))
    scored = []
    for past in session.scalars(
        select(Incident).where(Incident.id != incident.id, Incident.status.in_(["resolved", "rejected"]))
    ):
        if past.signature == incident.signature:
            scored.append((past, 1.0))
            continue
        tokens = _tokens(past.title)
        if not tokens or not query_tokens:
            continue
        jaccard = len(tokens & query_tokens) / len(tokens | query_tokens)
        if jaccard >= 0.3:
            scored.append((past, round(jaccard, 2)))
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]


def build_evidence_pack(session: Session, incident: Incident, service: Service, repo: GitRepo,
                        corr: CorrelationResult) -> dict[str, Any]:
    window_start = incident.first_seen - CONTEXT_WINDOW_BEFORE
    evidence: list[dict[str, Any]] = []

    # ---- LOG clusters (deduplicated) -------------------------------------------------
    rows = session.execute(
        select(LogEvent.signature, func.count(LogEvent.id), func.min(LogEvent.timestamp), func.max(LogEvent.timestamp))
        .where(LogEvent.service_id == service.id, LogEvent.timestamp >= window_start,
               LogEvent.timestamp <= incident.last_seen,
               LogEvent.level.in_(["WARNING", "ERROR", "CRITICAL", "FATAL"]))
        .group_by(LogEvent.signature)
        .order_by(func.count(LogEvent.id).desc())
    ).all()
    total_raw = sum(r[1] for r in rows)
    clusters = []
    for signature, count, first, last in rows[:MAX_CLUSTERS]:
        sig = session.scalar(select(LogSignature).where(LogSignature.service_id == service.id,
                                                        LogSignature.signature == signature))
        if signature == incident.signature:
            kind = "incident_signature"
        elif sig and sig.first_seen < incident.first_seen:
            kind = "pre_existing (already occurring before the incident began - likely background noise)"
        else:
            kind = "new (first appeared during the incident)"
        clusters.append({
            "id": f"LOG-{len(clusters) + 1}",
            "kind": "log_cluster",
            "classification": kind,
            "level": sig.level if sig else "",
            "template": sig.template if sig else "",
            "count_in_window": count,
            "first_seen": f"{first:%Y-%m-%d %H:%M:%S}",
            "last_seen": f"{last:%Y-%m-%d %H:%M:%S}",
            "first_ever_seen": f"{sig.first_seen:%Y-%m-%d %H:%M:%S}" if sig else "",
        })
    evidence.extend(clusters)

    # ---- representative stack trace + failing requests ------------------------------
    sample = session.scalar(
        select(LogEvent).where(LogEvent.service_id == service.id, LogEvent.signature == incident.signature,
                               LogEvent.stack_trace.is_not(None)).order_by(LogEvent.id.desc()).limit(1)
    )
    failing_requests = failing_request_samples(session, incident, limit=8)
    if sample:
        evidence.append({
            "id": "TRACE-1",
            "kind": "stack_trace",
            "exception": f"{sample.exception_type}: {sample.exception_message}",
            "logger": sample.logger,
            "stack_trace": compact_stack_trace(sample.stack_trace),
            "repo_frames": [f"{f.repo_path}:{f.line} in {f.function}()" for f in corr.frames],
            "sample_failing_requests": failing_requests,
        })

    # ---- deployments -------------------------------------------------------------------
    for i, dep in enumerate([d for d in (corr.suspect_deployment, corr.previous_deployment) if d]):
        evidence.append({
            "id": f"DEPLOY-{i + 1}",
            "kind": "deployment",
            "role": "last deployment before the incident" if i == 0 else "previous deployment",
            "version": dep.version,
            "commit": dep.commit_sha[:12],
            "deployed_at": f"{dep.deployed_at:%Y-%m-%d %H:%M:%S}",
        })

    # ---- suspect commits ----------------------------------------------------------------
    for s in corr.suspects[:MAX_COMMITS]:
        evidence.append({
            "id": f"COMMIT-{s.commit.sha[:7]}",
            "kind": "commit",
            "sha": s.commit.sha,
            "author": s.commit.author,
            "authored_at": f"{s.commit.authored_at:%Y-%m-%d %H:%M:%S}",
            "message": s.commit.message,
            "files_changed": s.commit.files,
            "correlation_score": s.score,
            "correlation_reasons": s.reasons,
            "diff": repo.diff_for_commit(s.commit.sha, context=3, max_chars=6000),
        })

    # ---- source code of the failing functions -------------------------------------------
    seen: set[tuple[str, int]] = set()
    for mf in reversed(corr.frames[-3:]):
        source = repo.file_at(corr.analysed_revision, mf.repo_path)
        if not source:
            continue
        start = mf.function_start or max(mf.line - 15, 1)
        end = mf.function_end or mf.line + 15
        if end - start > MAX_SNIPPET_LINES:
            start, end = max(mf.line - MAX_SNIPPET_LINES // 2, start), min(mf.line + MAX_SNIPPET_LINES // 2, end)
        if (mf.repo_path, start) in seen:
            continue
        seen.add((mf.repo_path, start))
        evidence.append({
            "id": f"CODE-{len(seen)}",
            "kind": "source_code",
            "file": mf.repo_path,
            "function": mf.function,
            "failing_line": mf.line,
            "revision": corr.analysed_revision[:12],
            "code": _numbered(source, start, end),
        })

    # ---- similar past incidents (retrieval) ----------------------------------------------
    for i, (past, sim) in enumerate(similar_incidents(session, incident)):
        rca = session.scalar(select(RCAReport).where(RCAReport.incident_id == past.id).order_by(RCAReport.id.desc()))
        patch = session.scalar(select(PatchProposal).where(PatchProposal.incident_id == past.id,
                                                           PatchProposal.status == "passed")
                               .order_by(PatchProposal.id.desc()))
        evidence.append({
            "id": f"INC-{past.id}",
            "kind": "past_incident",
            "similarity": sim,
            "title": past.title,
            "outcome": past.status,
            "root_cause": rca.probable_root_cause if rca else "",
            "fix_diff": (patch.diff[:3000] if patch else ""),
        })

    return {
        "incident": {
            "id": incident.id,
            "service": service.name,
            "title": incident.title,
            "first_seen": f"{incident.first_seen:%Y-%m-%d %H:%M:%S}",
            "last_seen": f"{incident.last_seen:%Y-%m-%d %H:%M:%S}",
            "event_count": incident.event_count,
            "detection_reason": incident.detection_reason,
        },
        "stats": {
            "raw_warning_and_error_events_in_window": total_raw,
            "distinct_clusters_in_window": len(rows),
            "clusters_included": len(clusters),
        },
        "analysed_revision": corr.analysed_revision,
        "correlation_notes": corr.notes,
        "evidence": evidence,
    }


def failing_request_samples(session: Session, incident: Incident, limit: int = 20) -> list[dict[str, Any]]:
    """Distinct HTTP requests that hit the incident's error (used for evidence and replay)."""
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for ev in session.scalars(
        select(LogEvent).where(LogEvent.service_id == incident.service_id, LogEvent.signature == incident.signature,
                               LogEvent.request.is_not(None)).order_by(LogEvent.id.desc()).limit(500)
    ):
        req = ev.request or {}
        key = (req.get("method"), req.get("path"), req.get("query"))
        if key in seen or not req.get("path"):
            continue
        seen.add(key)
        out.append({"method": req.get("method", "GET"), "path": req.get("path"), "query": req.get("query", ""),
                    "status": req.get("status")})
        if len(out) >= limit:
            break
    return out


def render_evidence(pack: dict[str, Any]) -> str:
    """Render the pack as readable, sectioned text for the prompt."""
    inc = pack["incident"]
    lines = [
        "# INCIDENT",
        f"Service: {inc['service']}",
        f"Title: {inc['title']}",
        f"First seen: {inc['first_seen']} UTC   Last seen: {inc['last_seen']} UTC   Events: {inc['event_count']}",
        f"Detection: {inc['detection_reason']}",
        f"Revision running in production when errors started: {pack['analysed_revision'][:12]}",
        f"Log volume in window: {pack['stats']['raw_warning_and_error_events_in_window']} warning/error events "
        f"deduplicated into {pack['stats']['distinct_clusters_in_window']} clusters.",
    ]
    for note in pack.get("correlation_notes", []):
        lines.append(f"Note: {note}")
    lines.append("\n# EVIDENCE (cite these IDs)")
    for ev in pack["evidence"]:
        lines.append(f"\n## [{ev['id']}] {ev['kind']}")
        for key, value in ev.items():
            if key in ("id", "kind"):
                continue
            if isinstance(value, str) and "\n" in value:
                lines.append(f"{key}:\n```\n{value.rstrip()}\n```")
            elif isinstance(value, list):
                if value and isinstance(value[0], dict):
                    lines.append(f"{key}:")
                    lines.extend(f"  - {item}" for item in value)
                else:
                    lines.append(f"{key}: {', '.join(map(str, value)) if value else '(none)'}")
            else:
                lines.append(f"{key}: {value}")
    return "\n".join(lines)
