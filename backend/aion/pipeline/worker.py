"""Background job execution.

A single-thread executor runs pipeline and deployment jobs one at a time.
One worker is deliberate: jobs are long (LLM calls, test runs) but rare, and
serialising them avoids two jobs fighting over the same git repository or
SQLite writer lock. A queue such as Celery/RQ is the upgrade path when AION
must handle many services concurrently (see DECISIONS.md).
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

log = logging.getLogger("aion.worker")


class Worker:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aion-worker")
        self._lock = threading.Lock()
        self._inflight: dict[str, Future] = {}

    def submit(self, key: str, fn: Callable[[], None]) -> bool:
        """Queue `fn` unless a job with the same key is already queued/running."""
        with self._lock:
            existing = self._inflight.get(key)
            if existing is not None and not existing.done():
                return False
            future = self._executor.submit(self._wrap, key, fn)
            self._inflight[key] = future
            return True

    def _wrap(self, key: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:
            log.exception("job %s failed", key)

    def busy_keys(self) -> list[str]:
        with self._lock:
            return [k for k, f in self._inflight.items() if not f.done()]

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


worker = Worker()


def enqueue_pipeline(incident_id: int) -> bool:
    from aion.pipeline.orchestrator import run_pipeline

    return worker.submit(f"incident-{incident_id}", lambda: run_pipeline(incident_id))


def enqueue_deploy(incident_id: int, deployed_by: str) -> bool:
    from aion.pipeline.orchestrator import run_deploy

    return worker.submit(f"deploy-{incident_id}", lambda: run_deploy(incident_id, deployed_by))


def enqueue_rollback(incident_id: int, actor: str) -> bool:
    from aion.pipeline.orchestrator import run_rollback

    return worker.submit(f"rollback-{incident_id}", lambda: run_rollback(incident_id, actor))
