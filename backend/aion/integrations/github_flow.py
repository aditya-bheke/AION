"""The GitHub steps of the workflow: open the PR, track Actions, gate approval, push on deploy.

Network calls are made outside database transactions (they can take seconds), and every
outcome - including failures - is written to the audit trail. A GitHub failure never deploys
anything; at worst it blocks approval/deployment with a clear reason.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from aion import audit
from aion.config import settings
from aion.db import session_scope
from aion.integrations.github import GitHubError, github_for
from aion.models import (Incident, PatchProposal, PullRequest, RCAReport, Service, ValidationRun, utcnow)

log = logging.getLogger("aion.github")


def _pr_body(incident: Incident, service: Service, patch: PatchProposal, rca: Optional[RCAReport],
             run: Optional[ValidationRun]) -> str:
    lines = [
        f"## AION fix for incident #{incident.id} — {incident.title}",
        "",
        "> ⚠️ **Do not merge manually.** This change is deployed only through AION, after a signed-in human "
        "approver has reviewed it. AION then fast-forwards `main` to exactly this commit.",
        "",
        f"**Service:** `{service.name}` · **Strategy:** {patch.strategy} ({patch.generator}) · "
        f"**Commit:** `{patch.commit_sha[:10]}`",
        "",
    ]
    if rca:
        lines += ["### Root cause", rca.probable_root_cause, "",
                  f"Confidence **{rca.confidence:.2f}** · analyzer `{rca.analyzer}` · suspected commit "
                  f"`{(rca.suspected_commit or 'n/a')[:10]}`", ""]
    if patch.rationale:
        lines += ["### Rationale", patch.rationale[:3000], ""]
    if run:
        lines += ["### AION validation", "| Step | Result | Summary |", "|---|---|---|"]
        lines += [f"| {s['title']} | {s['status']} | {s['summary'][:150]} |" for s in run.steps]
        lines.append("")
    lines.append("_Opened automatically by AION. GitHub Actions on this PR is an additional CI gate._")
    return "\n".join(lines)


def open_pull_request(incident_id: int, patch_id: int) -> Optional[int]:
    """Push the validated branch and open a PR. Returns the PullRequest row id, or None."""
    with session_scope() as s:
        incident = s.get(Incident, incident_id)
        service = s.get(Service, incident.service_id)
        patch = s.get(PatchProposal, patch_id)
        gh = github_for(service)
        if gh is None:
            return None
        rca = s.scalar(select(RCAReport).where(RCAReport.incident_id == incident_id).order_by(RCAReport.id.desc()))
        run = s.scalar(select(ValidationRun).where(ValidationRun.patch_id == patch_id).order_by(ValidationRun.id.desc()))
        title = f"AION fix for incident #{incident.id}: {incident.title}"[:240]
        body = _pr_body(incident, service, patch, rca, run)
        repo_path, branch, base, sha = service.repo_path, patch.branch, service.production_branch, patch.commit_sha
    try:
        from pathlib import Path

        gh.push(Path(repo_path), f"{branch}:refs/heads/{branch}", force=True)  # AION-owned branch
        pr = gh.open_pull_request(branch, base, title, body)
    except GitHubError as exc:
        with session_scope() as s:
            audit.record(s, "github_pr_failed", "system:github", incident_id=incident_id, error=str(exc)[:500])
        log.warning("could not open PR for incident %s: %s", incident_id, exc)
        return None
    with session_scope() as s:
        row = PullRequest(incident_id=incident_id, patch_id=patch_id, repo=gh.repo, number=pr["number"],
                          url=pr["html_url"], branch=branch, head_sha=sha, state="open", ci_state="pending")
        s.add(row)
        s.flush()
        audit.record(s, "github_pr_opened", "system:github", incident_id=incident_id, number=pr["number"],
                     url=pr["html_url"], branch=branch)
        return row.id


def refresh_pull_request(pr_id: int) -> None:
    """Update CI status (GitHub Actions runs for the head commit) and merged state."""
    with session_scope() as s:
        pr = s.get(PullRequest, pr_id)
        service = s.get(Service, s.get(Incident, pr.incident_id).service_id)
        gh, number, sha, before = github_for(service), pr.number, pr.head_sha, pr.ci_state
    if gh is None:
        return
    try:
        ci = gh.ci_status(sha)
        info = gh.pull_request(number)
    except GitHubError as exc:
        log.warning("GitHub refresh failed for PR %s: %s", number, exc)
        return
    with session_scope() as s:
        pr = s.get(PullRequest, pr_id)
        pr.ci_state, pr.ci_runs, pr.ci_checked_at = ci.state, ci.runs, utcnow()
        pr.state = "merged" if info.get("merged") else ("closed" if info.get("state") == "closed" else "open")
        if ci.state != before and ci.state in ("success", "failure"):
            audit.record(s, "github_ci_completed", "system:github", incident_id=pr.incident_id, number=pr.number,
                         result=ci.state, runs=len(ci.runs))


def latest_pr(session: Session, incident_id: int) -> Optional[PullRequest]:
    return session.scalar(select(PullRequest).where(PullRequest.incident_id == incident_id)
                          .order_by(PullRequest.id.desc()))


def ci_gate(session: Session, incident_id: int, patch: PatchProposal) -> Optional[str]:
    """Reason why GitHub CI blocks approval/deployment of `patch`, or None if it doesn't."""
    if not settings.require_github_ci:
        return None
    pr = latest_pr(session, incident_id)
    if pr is None or pr.patch_id != patch.id:
        return None  # no PR for this patch (GitHub not linked, or PR could not be opened)
    if pr.ci_state == "success":
        return None
    return f"GitHub Actions on PR #{pr.number} has not passed yet (state: {pr.ci_state})"


def push_production(service: Service, commit_sha: str) -> Optional[str]:
    """Fast-forward GitHub's production branch to `commit_sha` (non-force). Returns None or an error."""
    gh = github_for(service)
    if gh is None:
        return None
    from pathlib import Path

    try:
        gh.push(Path(service.repo_path), f"{commit_sha}:refs/heads/{service.production_branch}")
    except GitHubError as exc:
        return str(exc)
    return None
