"""The automated incident pipeline.

    detected -> analyzing -> patching -> validating -> awaiting_approval
                                 ^            |
                                 +-- retry ---+   (generate-validate-repair, bounded)

Each stage commits its results before the next one starts, so the dashboard
shows progress live and a crash leaves a precise record of where it stopped.
The pipeline ends at `awaiting_approval`: nothing in this module can deploy.
"""
from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import delete, select

from aion import audit
from aion.ai.context import build_evidence_pack, failing_request_samples
from aion.ai.providers.base import LLMError
from aion.ai.providers.factory import get_provider
from aion.ai.rca import RCAOutput, ground, run_heuristic_rca, run_llm_rca
from aion.config import settings
from aion.db import session_scope
from aion.gitops.correlation import DeploymentInfo, correlate
from aion.gitops.repo import GitRepo
from aion.lifecycle import Status, transition
from aion.models import CommitSuspect, Deployment, Incident, LogEvent, PatchProposal, RCAReport, Service, ValidationRun, utcnow
from aion.remediation.service import create_patch
from aion.validation.runner import ValidationRunner, ValidationTarget

log = logging.getLogger("aion.pipeline")


def _baseline_requests(session, incident: Incident, limit: int = 10) -> list[dict[str, Any]]:
    """Distinct successful GET requests seen recently - replayed to catch regressions."""
    seen, out = set(), []
    for ev in session.scalars(select(LogEvent).where(LogEvent.service_id == incident.service_id,
                                                     LogEvent.request.is_not(None))
                              .order_by(LogEvent.id.desc()).limit(2000)):
        req = ev.request or {}
        status = req.get("status")
        if not isinstance(status, int) or status >= 400 or req.get("method", "GET") != "GET":
            continue
        key = (req.get("path"), req.get("query"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"method": "GET", "path": req.get("path"), "query": req.get("query", ""), "status": status})
        if len(out) >= limit:
            break
    return out


def _feedback_from(steps: list[dict[str, Any]]) -> str:
    failed = [s for s in steps if s["status"] == "failed"]
    parts = []
    for s in failed:
        parts.append(f"Validation step '{s['title']}' failed: {s['summary']}\n```\n{s['output'][-3000:]}\n```")
    return "\n\n".join(parts) or "Validation failed."


def run_pipeline(incident_id: int) -> None:
    try:
        _run(incident_id)
    except Exception as exc:  # record, never crash the worker thread
        log.exception("pipeline crashed for incident %s", incident_id)
        with session_scope() as session:
            incident = session.get(Incident, incident_id)
            if incident and incident.status not in (Status.ERROR.value, Status.AWAITING_APPROVAL.value,
                                                    Status.VALIDATION_FAILED.value):
                incident.pipeline_error = f"{exc}\n\n{traceback.format_exc()[-3000:]}"
                try:
                    transition(session, incident, Status.ERROR, "system:pipeline", error=str(exc)[:500])
                except Exception:
                    incident.status = Status.ERROR.value


def _run(incident_id: int) -> None:
    provider = get_provider(settings)

    # ---- Stage 1: investigation (correlation) -------------------------------------
    with session_scope() as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            return
        service = session.get(Service, incident.service_id)
        transition(session, incident, Status.ANALYZING, "system:pipeline")
        incident.pipeline_error = None
        repo = GitRepo(service.repo_path)
        if not repo.is_repo():
            raise RuntimeError(f"Service repository not found or not a git repo: {service.repo_path}")

        sample = session.scalar(select(LogEvent).where(LogEvent.service_id == service.id,
                                                       LogEvent.signature == incident.signature,
                                                       LogEvent.stack_trace.is_not(None))
                                .order_by(LogEvent.id.desc()).limit(1))
        deployments = [DeploymentInfo(d.version, d.commit_sha, d.deployed_at) for d in session.scalars(
            select(Deployment).where(Deployment.service_id == service.id, Deployment.environment == "production",
                                     Deployment.status.in_(["succeeded", "verifying"])))]
        corr = correlate(repo, service.production_branch, sample.frames if sample else [],
                         [incident.title], incident.first_seen, deployments)
        session.execute(delete(CommitSuspect).where(CommitSuspect.incident_id == incident.id))
        for s in corr.suspects[:10]:
            session.add(CommitSuspect(incident_id=incident.id, commit_sha=s.commit.sha, author=s.commit.author,
                                      authored_at=s.commit.authored_at, message=s.commit.message,
                                      files_changed=s.commit.files, score=s.score, reasons=s.reasons,
                                      deployment_version=s.deployment_version))
        audit.record(session, "correlation_completed", "system:correlator", incident_id=incident.id,
                     candidates=len(corr.suspects),
                     top_suspect=corr.suspects[0].commit.sha if corr.suspects else None,
                     top_score=corr.suspects[0].score if corr.suspects else None)

        # ---- Stage 2: root-cause analysis ---------------------------------------------
        pack = build_evidence_pack(session, incident, service, repo, corr)
        repo_files = set(repo.ls_files(corr.analysed_revision))
        if provider:
            try:
                result = run_llm_rca(provider, pack)
            except LLMError as exc:
                # Keep the workflow usable when the model is unavailable, and say so loudly.
                result = run_heuristic_rca(pack)
                result.warnings.append(f"LLM analysis failed ({exc}); fell back to the deterministic analyzer.")
                provider_for_patch = None
            else:
                provider_for_patch = provider
        else:
            result = run_heuristic_rca(pack)
            provider_for_patch = None
        result = ground(result, pack, repo_files)
        out = result.output
        rca_row = RCAReport(
            incident_id=incident.id, analyzer=result.analyzer, probable_root_cause=out.probable_root_cause,
            observed_evidence=[o.model_dump() for o in out.observed_evidence],
            inferences=[i.model_dump() for i in out.inferences], affected_service=out.affected_service,
            affected_files=out.affected_files, suspected_commit=out.suspected_commit or None,
            confidence=out.confidence, remediation=out.remediation, grounding_warnings=result.warnings,
            evidence_pack=pack, raw_response=result.raw_text,
            usage=dict(result.usage, confidence_rationale=out.confidence_rationale,
                       alternative_hypotheses=out.alternative_hypotheses))
        session.add(rca_row)
        session.flush()
        actor = "system:heuristic-analyzer" if result.analyzer.startswith("heuristic") else f"ai:{result.analyzer}"
        audit.record(session, "rca_completed", actor, incident_id=incident.id, rca_id=rca_row.id,
                     confidence=out.confidence, suspected_commit=out.suspected_commit,
                     grounding_warnings=len(result.warnings))
        transition(session, incident, Status.PATCHING, "system:pipeline")
        rca_output: RCAOutput = out
        failing = failing_request_samples(session, incident)
        baseline = _baseline_requests(session, incident)
        previous_attempts = session.scalar(select(PatchProposal.attempt).where(PatchProposal.incident_id == incident.id)
                                           .order_by(PatchProposal.attempt.desc()).limit(1)) or 0

    # ---- Stage 3+4: patch -> validate, with bounded repair loop ----------------------
    # The attempt plan: N AI attempts (each one sees the previous failure), then - if the
    # RCA named a suspect commit - a deterministic revert as the last resort, like an
    # on-call engineer rolling back when a forward fix doesn't hold. No LLM: revert only.
    plan: list[Optional[Any]] = ([provider_for_patch] * settings.max_patch_attempts if provider_for_patch
                                 else [None])
    if provider_for_patch and settings.revert_fallback and rca_output.suspected_commit:
        plan.append(None)
    feedback: Optional[str] = None
    for n, patch_provider in enumerate(plan, start=1):
        attempt = previous_attempts + n
        last = n == len(plan)
        with session_scope() as session:
            incident = session.get(Incident, incident_id)
            service = session.get(Service, incident.service_id)
            if provider_for_patch and patch_provider is None:
                audit.record(session, "revert_fallback", "system:pipeline", incident_id=incident.id,
                             reason=f"{n - 1} AI patch attempt(s) failed validation",
                             commit=rca_output.suspected_commit)
            patch = create_patch(session, incident, service, rca_output, pack, failing, attempt, feedback,
                                 patch_provider)
            if provider_for_patch and patch_provider is None:
                patch.generator = f"deterministic git revert (fallback after {n - 1} failed AI attempts)"
            patch_id = patch.id
            if patch.status != "ready":
                feedback = f"Your patch could not be applied: {patch.error}"
                if last:
                    transition(session, incident, Status.VALIDATION_FAILED, "system:pipeline",
                               reason="no applicable patch", error=patch.error)
                    return
                continue
            transition(session, incident, Status.VALIDATING, "system:pipeline", patch_id=patch.id)
            run = ValidationRun(incident_id=incident.id, patch_id=patch.id, status="running")
            session.add(run)
            session.flush()
            run_id = run.id
            target = ValidationTarget(
                repo_path=service.repo_path, worktree=Path(patch.worktree_path),
                base_sha=patch.base_sha, commit_sha=patch.commit_sha, test_command=service.test_command,
                run_command=service.run_command, health_path=service.health_path,
                new_test_files=[e["path"] for e in patch.edits if e.get("new_file")],
                failing_requests=failing, baseline_requests=baseline)

        def progress(steps: list[dict[str, Any]], _run_id=run_id) -> None:
            with session_scope() as s:
                s.get(ValidationRun, _run_id).steps = steps

        passed, steps = ValidationRunner(target, progress).run()

        with session_scope() as session:
            incident = session.get(Incident, incident_id)
            run = session.get(ValidationRun, run_id)
            patch = session.get(PatchProposal, patch_id)
            run.steps, run.status, run.finished_at = steps, ("passed" if passed else "failed"), utcnow()
            patch.status = "passed" if passed else "failed"
            audit.record(session, "validation_completed", "system:validator", incident_id=incident.id,
                         patch_id=patch.id, passed=passed,
                         steps={s["name"]: s["status"] for s in steps})
            if passed:
                transition(session, incident, Status.AWAITING_APPROVAL, "system:pipeline", patch_id=patch.id,
                           note="Validated patch is ready. Production deployment requires human approval.")
                return
            feedback = _feedback_from(steps)
            if not last:
                transition(session, incident, Status.PATCHING, "system:pipeline", reason="validation failed; retrying")
                continue
            transition(session, incident, Status.VALIDATION_FAILED, "system:pipeline", patch_id=patch.id)
            return


def run_deploy(incident_id: int) -> None:
    """Deploy the approved patch. Only reachable from state DEPLOYING (set by the human-approval API)."""
    from aion.deploy.deployer import DeploymentBlocked, deploy

    with session_scope() as session:
        incident = session.get(Incident, incident_id)
        service = session.get(Service, incident.service_id)
        patch = session.scalar(select(PatchProposal).where(PatchProposal.incident_id == incident_id,
                                                           PatchProposal.status == "passed")
                               .order_by(PatchProposal.id.desc()))
        try:
            if incident.status != Status.DEPLOYING.value:
                raise DeploymentBlocked(f"Incident is in state {incident.status!r}, not 'deploying'")
            if patch is None:
                raise DeploymentBlocked("No validated patch found")
            outcome = deploy(session, incident, service, patch)
        except DeploymentBlocked as exc:
            audit.record(session, "deployment_blocked", "system:deployer", incident_id=incident_id, reason=str(exc))
            incident.pipeline_error = f"Deployment blocked: {exc}"
            if incident.status == Status.DEPLOYING.value:
                transition(session, incident, Status.DEPLOY_FAILED, "system:deployer", reason=str(exc))
            return
        except Exception as exc:
            log.exception("deployment crashed for incident %s", incident_id)
            incident.pipeline_error = f"Deployment error: {exc}"
            audit.record(session, "deployment_error", "system:deployer", incident_id=incident_id, error=str(exc)[:500])
            transition(session, incident, Status.DEPLOY_FAILED, "system:deployer", reason=str(exc)[:300])
            return
        patch.status = "deployed" if outcome.success else patch.status
        audit.record(session, "deployment_completed" if outcome.success else "deployment_verification_failed",
                     "system:deployer", incident_id=incident_id, deployment_id=outcome.deployment_id,
                     commit=patch.commit_sha, message=outcome.message, checks=outcome.verification)
        if outcome.success:
            transition(session, incident, Status.RESOLVED, "system:deployer", deployment_id=outcome.deployment_id)
        else:
            incident.pipeline_error = outcome.message
            transition(session, incident, Status.DEPLOY_FAILED, "system:deployer", reason=outcome.message)
