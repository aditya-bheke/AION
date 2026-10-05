"""Services, log ingestion and deployment-history endpoints."""
from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from aion import audit
from aion.api import serializers as ser
from aion.config import settings
from aion.db import get_session
from aion.gitops.repo import GitRepo
from aion.logs.ingest import ingest_events
from aion.integrations.github import normalize_repo
from aion.models import Deployment, Service, ServiceGitHub
from aion.pipeline.worker import enqueue_pipeline
from aion.schemas import DeploymentIn, IngestIn, ServiceIn
from aion.security import Principal, require_role, require_service_or_admin

router = APIRouter(prefix="/api", tags=["ingest"])


def _service_or_404(session: Session, name: str) -> Service:
    svc = session.scalar(select(Service).where(Service.name == name))
    if svc is None:
        raise HTTPException(404, f"Unknown service {name!r}; register it with POST /api/services first")
    return svc


@router.post("/services")
def register_service(body: ServiceIn, session: Session = Depends(get_session),
                     client: Principal = Depends(require_service_or_admin)):
    if not GitRepo(body.repo_path).is_repo():
        raise HTTPException(422, f"repo_path {body.repo_path!r} is not a git repository")
    svc = session.scalar(select(Service).where(Service.name == body.name))
    created = svc is None
    if created:
        svc = Service(name=body.name, repo_path=body.repo_path)
        session.add(svc)
    for field, value in body.model_dump(exclude={"github_repo"}).items():
        if field == "log_path" and svc.log_path != value:
            svc.collector_offset = 0
        setattr(svc, field, value)
    session.flush()
    repo_link = body.github_repo or settings.github_repo
    if repo_link:
        try:
            repo_link = normalize_repo(repo_link)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        link = session.scalar(select(ServiceGitHub).where(ServiceGitHub.service_id == svc.id))             or ServiceGitHub(service_id=svc.id, repo=repo_link)
        link.repo = repo_link
        session.add(link)
    audit.record(session, "service_registered" if created else "service_updated", client.actor, service=svc.name)
    return ser.service(svc)


@router.get("/services")
def list_services(session: Session = Depends(get_session), _: Principal = Depends(require_role("viewer"))):
    return [ser.service(s) for s in session.scalars(select(Service).order_by(Service.name))]


@router.post("/ingest/{service_name}")
def ingest(service_name: str, body: IngestIn, session: Session = Depends(get_session),
           _: Principal = Depends(require_service_or_admin)):
    svc = _service_or_404(session, service_name)
    result = ingest_events(session, svc, body.events)
    session.commit()  # the pipeline runs on another thread: data must be committed first
    if settings.auto_pipeline:
        for incident_id in result.new_incident_ids:
            enqueue_pipeline(incident_id)
    return {"accepted": result.accepted, "rejected": result.rejected, "errors": result.errors,
            "new_incidents": result.new_incident_ids}


@router.post("/deployments")
def record_deployment(body: DeploymentIn, session: Session = Depends(get_session),
                      _: Principal = Depends(require_service_or_admin)):
    """Called by CI/CD (or the demo setup) whenever a version goes live."""
    svc = _service_or_404(session, body.service)
    repo = GitRepo(svc.repo_path)
    try:
        sha = repo.rev_parse(body.commit_sha)
    except Exception:
        raise HTTPException(422, f"Commit {body.commit_sha!r} not found in {svc.repo_path}")
    deployed_at = body.deployed_at
    if deployed_at and deployed_at.tzinfo:
        deployed_at = deployed_at.astimezone(timezone.utc).replace(tzinfo=None)
    dep = Deployment(service_id=svc.id, environment=body.environment, version=body.version, commit_sha=sha,
                     deployed_by=body.deployed_by, notes=body.notes)
    if deployed_at:
        dep.deployed_at = deployed_at
    session.add(dep)
    session.flush()
    audit.record(session, "deployment_recorded", f"system:{body.deployed_by}", service=svc.name,
                 version=body.version, commit=sha, environment=body.environment)
    return ser.deployment(dep)


@router.get("/deployments")
def list_deployments(service: str | None = None, session: Session = Depends(get_session),
                     _: Principal = Depends(require_role("viewer"))):
    q = select(Deployment).order_by(Deployment.deployed_at.desc())
    if service:
        q = q.where(Deployment.service_id == _service_or_404(session, service).id)
    return [ser.deployment(d) for d in session.scalars(q.limit(100))]
