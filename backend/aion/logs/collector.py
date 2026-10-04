"""File-tail log collector (a tiny Filebeat/Promtail equivalent).

For every registered service that has a `log_path`, read any bytes appended
since the last poll, parse them as JSON lines and ingest them. The byte offset
is stored in the database so a restart of AION does not re-ingest old lines.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Callable

from sqlalchemy import select

from aion.db import session_scope
from aion.logs.ingest import ingest_events
from aion.models import Service

log = logging.getLogger("aion.collector")


def poll_once(on_new_incidents: Callable[[list[int]], None] | None = None) -> int:
    """Read new lines from every service log file. Returns number of events ingested."""
    total = 0
    with session_scope() as session:
        services = session.scalars(select(Service).where(Service.log_path.is_not(None))).all()
        for service in services:
            path = service.log_path
            if not path or not os.path.exists(path):
                continue
            size = os.path.getsize(path)
            if size < service.collector_offset:  # file was truncated / rotated
                service.collector_offset = 0
            if size == service.collector_offset:
                continue
            with open(path, "rb") as fh:
                fh.seek(service.collector_offset)
                chunk = fh.read()
            # Only consume complete lines; a half-written last line waits for the next poll.
            last_newline = chunk.rfind(b"\n")
            if last_newline == -1:
                continue
            complete = chunk[: last_newline + 1]
            events = []
            for line in complete.decode("utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    # Unstructured line: keep it rather than silently dropping it.
                    events.append({"level": "INFO", "message": line})
            result = ingest_events(session, service, events)
            service.collector_offset += len(complete)
            total += result.accepted
            if result.new_incident_ids and on_new_incidents:
                session.commit()
                on_new_incidents(result.new_incident_ids)
    return total


class CollectorThread(threading.Thread):
    def __init__(self, interval: float, on_new_incidents: Callable[[list[int]], None]):
        super().__init__(name="aion-collector", daemon=True)
        self.interval = interval
        self.on_new_incidents = on_new_incidents
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                poll_once(self.on_new_incidents)
            except Exception:  # never let the collector die
                log.exception("log collector poll failed")
            self._stop_event.wait(self.interval)

    def stop(self) -> None:
        self._stop_event.set()
