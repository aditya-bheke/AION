from datetime import datetime, timedelta

from sqlalchemy import func, select

from aion.config import settings
from aion.db import session_scope
from aion.logs.ingest import ingest_events
from aion.models import Incident, Service

T0 = datetime(2026, 10, 4, 10, 0, 0)


def _svc(session):
    svc = Service(name="svc", repo_path=".")
    session.add(svc)
    session.flush()
    return svc


def _err(ts, msg="boom", etype="TypeError"):
    return {"timestamp": ts.isoformat(), "level": "ERROR", "message": "Unhandled exception",
            "exception": {"type": etype, "message": msg, "stacktrace": ""}}


def test_new_error_burst_opens_one_incident(aion_env):
    with session_scope() as s:
        svc = _svc(s)
        r1 = ingest_events(s, svc, [_err(T0 + timedelta(seconds=i)) for i in range(settings.detection_min_count - 1)])
        assert r1.new_incident_ids == []  # below threshold
        r2 = ingest_events(s, svc, [_err(T0 + timedelta(seconds=10))])
        assert len(r2.new_incident_ids) == 1
        r3 = ingest_events(s, svc, [_err(T0 + timedelta(seconds=11 + i)) for i in range(10)])
        assert r3.new_incident_ids == []  # deduplicated into the open incident
        inc = s.get(Incident, r2.new_incident_ids[0])
        assert inc.event_count == settings.detection_min_count + 10
        assert inc.severity == "high"  # never seen before


def test_steady_background_error_does_not_fire(aion_env):
    with session_scope() as s:
        svc = _svc(s)
        # 6 per minute for the last 30 minutes: frequent, but it is the normal baseline.
        history = [_err(T0 - timedelta(seconds=10 * i), msg="gateway timeout", etype="Timeout") for i in range(1, 180)]
        ingest_events(s, svc, history)
        r = ingest_events(s, svc, [_err(T0 + timedelta(seconds=i * 10), msg="gateway timeout", etype="Timeout")
                                   for i in range(6)])
        assert r.new_incident_ids == []
        assert s.scalar(select(func.count(Incident.id))) == 0


def test_info_logs_never_open_incidents(aion_env):
    with session_scope() as s:
        svc = _svc(s)
        r = ingest_events(s, svc, [{"timestamp": (T0 + timedelta(seconds=i)).isoformat(), "level": "INFO",
                                    "message": f"GET /x/{i} -> 200"} for i in range(50)])
        assert r.new_incident_ids == []
        assert r.accepted == 50


def test_late_lines_after_resolution_do_not_reopen_but_regression_does(aion_env):
    from aion.models import utcnow

    with session_scope() as s:
        svc = _svc(s)
        base = utcnow() - timedelta(seconds=30)
        r = ingest_events(s, svc, [_err(base + timedelta(seconds=i)) for i in range(6)])
        inc = s.get(Incident, r.new_incident_ids[0])
        inc.status = "resolved"
        s.flush()
        resolved_at = inc.updated_at
        # Lines written before the fix went live, but collected after resolution.
        late = ingest_events(s, svc, [_err(base + timedelta(seconds=10 + i)) for i in range(6)])
        assert late.new_incident_ids == []
        # The same error genuinely happening again after the fix -> regression incident.
        again = ingest_events(s, svc, [_err(resolved_at + timedelta(seconds=1 + i)) for i in range(6)])
        assert len(again.new_incident_ids) == 1
