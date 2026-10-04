"""FastAPI application factory and process lifecycle."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from aion.api import incidents, ingest, system
from aion.config import REPO_ROOT, settings
from aion.db import init_engine, session_scope
from aion.lifecycle import InvalidTransition, Status, transition
from aion.logs.collector import CollectorThread
from aion.models import Incident

log = logging.getLogger("aion")

# States whose job lives only in memory; after a restart that job is gone.
_INTERRUPTIBLE = {Status.ANALYZING: Status.ERROR, Status.PATCHING: Status.ERROR,
                  Status.VALIDATING: Status.ERROR, Status.DEPLOYING: Status.DEPLOY_FAILED}


def _recover_interrupted_jobs() -> None:
    with session_scope() as session:
        for inc in session.scalars(select(Incident).where(Incident.status.in_([s.value for s in _INTERRUPTIBLE]))):
            target = _INTERRUPTIBLE[Status(inc.status)]
            inc.pipeline_error = f"Interrupted by an AION restart while {inc.status}; re-run when ready."
            transition(session, inc, target, "system:startup")


def create_app(start_background: Optional[bool] = None) -> FastAPI:
    background = settings.enable_background if start_background is None else start_background

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_engine(settings.database_url)
        settings.worktrees_dir.mkdir(parents=True, exist_ok=True)
        collector = None
        if background:
            _recover_interrupted_jobs()
            from aion.pipeline.worker import enqueue_pipeline

            def on_new(ids: list[int]) -> None:
                if settings.auto_pipeline:
                    for i in ids:
                        enqueue_pipeline(i)

            collector = CollectorThread(settings.collector_interval_seconds, on_new)
            collector.start()
        yield
        if collector:
            collector.stop()

    app = FastAPI(title="AION", version="0.1.0", lifespan=lifespan,
                  description="Autonomous Incident Observation & Navigation")

    @app.exception_handler(InvalidTransition)
    async def _invalid_transition(_: Request, exc: InvalidTransition):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    app.include_router(system.router)
    app.include_router(ingest.router)
    app.include_router(incidents.router)

    dist = REPO_ROOT / "frontend" / "dist"
    if dist.exists():  # production build of the dashboard, served by the same process
        app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
    return app
