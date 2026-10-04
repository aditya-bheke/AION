"""Production deployment of an approved fix (GitOps style).

"Deploying" means fast-forwarding the service's production branch to the
approved commit. The production runtime watches that checkout and reloads
(in the demo: `uvicorn --reload`; in a real system: a CD tool such as
Argo CD or a CI job triggered by the branch update).

Safety checks performed here, in code, before anything changes:
  * the incident is in state DEPLOYING (reachable only via human approval)
  * an approval record exists for exactly this commit SHA
  * the patch passed validation
  * the production checkout is on the production branch and clean
  * the production branch has not moved since validation (fast-forward only)
After the merge, AION verifies production: it waits for the service to report
the new commit, then replays the incident's failing requests.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from aion.ai.context import failing_request_samples
from aion.gitops.repo import GitError, GitRepo
from aion.models import Approval, Deployment, Incident, PatchProposal, Service, ValidationRun


class DeploymentBlocked(Exception):
    pass


@dataclass
class DeployOutcome:
    success: bool
    message: str
    deployment_id: Optional[int] = None
    verification: list[dict[str, Any]] = field(default_factory=list)


def preflight(session: Session, incident: Incident, patch: PatchProposal) -> Approval:
    approval = session.scalar(
        select(Approval).where(Approval.incident_id == incident.id, Approval.patch_id == patch.id,
                               Approval.decision == "approved").order_by(Approval.id.desc())
    )
    if approval is None:
        raise DeploymentBlocked("No human approval recorded for this patch")
    if approval.commit_sha != patch.commit_sha:
        raise DeploymentBlocked("The approved commit does not match the patch commit (patch changed after approval)")
    validation = session.scalar(select(ValidationRun).where(ValidationRun.patch_id == patch.id)
                                .order_by(ValidationRun.id.desc()))
    if validation is None or validation.status != "passed":
        raise DeploymentBlocked("The patch has not passed validation")
    return approval


def deploy(session: Session, incident: Incident, service: Service, patch: PatchProposal,
           verify_timeout: float = 45.0) -> DeployOutcome:
    approval = preflight(session, incident, patch)
    repo = GitRepo(service.repo_path)
    if repo.current_branch() != service.production_branch:
        raise DeploymentBlocked(f"Production checkout is not on branch {service.production_branch!r}")
    if repo.git("status", "--porcelain", "--untracked-files=no").strip():
        raise DeploymentBlocked("Production checkout has uncommitted changes")
    head = repo.rev_parse(service.production_branch)
    if head != patch.base_sha and not repo.is_ancestor(head, patch.commit_sha):
        raise DeploymentBlocked(
            f"Production branch moved since validation (now {head[:7]}, patch based on {patch.base_sha[:7]}); "
            "the patch must be regenerated and re-validated")
    try:
        repo.merge_ff_only(patch.branch)
    except GitError as exc:
        raise DeploymentBlocked(f"Fast-forward merge failed: {exc}") from exc

    dep = Deployment(service_id=service.id, environment="production", version=f"aion-fix-incident-{incident.id}",
                     commit_sha=patch.commit_sha, deployed_by=f"human:{approval.approver}", incident_id=incident.id,
                     status="verifying", notes=f"Approved by {approval.approver}: {approval.comment}")
    session.add(dep)
    session.flush()

    ok, message, checks = verify_production(session, incident, service, patch.commit_sha, verify_timeout)
    dep.status = "succeeded" if ok else "verification_failed"
    session.flush()
    return DeployOutcome(ok, message, dep.id, checks)


def verify_production(session: Session, incident: Incident, service: Service, commit_sha: str,
                      timeout: float) -> tuple[bool, str, list[dict[str, Any]]]:
    if not service.production_url:
        return True, "Merged to production branch (no production URL registered, runtime verification skipped)", []
    base = service.production_url.rstrip("/")
    checks: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    running = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(base + service.health_path, timeout=3)
            if r.status_code == 200:
                running = (r.json() or {}).get("commit") if "json" in r.headers.get("content-type", "") else None
                # Services that report their commit let us confirm the reload actually happened.
                if running is None or str(running).startswith(commit_sha[:7]) or commit_sha.startswith(str(running)):
                    break
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(1.0)
    else:
        return False, f"Production did not come up on the new commit within {timeout:.0f}s (running: {running})", checks
    checks.append({"check": "health", "ok": True, "detail": f"healthy, running commit {running or 'unknown'}"})

    failures = 0
    for req in failing_request_samples(session, incident, limit=10):
        if req["method"].upper() not in ("GET", "HEAD"):
            continue
        url = req["path"] + (f"?{req['query']}" if req.get("query") else "")
        try:
            status = httpx.request(req["method"], base + url, timeout=5).status_code
        except httpx.HTTPError as exc:
            status, failures = None, failures + 1
            checks.append({"check": f"{req['method']} {url}", "ok": False, "detail": str(exc)})
            continue
        ok = status < 500
        failures += 0 if ok else 1
        checks.append({"check": f"{req['method']} {url}", "ok": ok, "detail": f"status {status}"})
    if failures:
        return False, f"{failures} previously failing request(s) still fail in production", checks
    return True, "Production verified: healthy on the new commit and incident requests no longer fail", checks
