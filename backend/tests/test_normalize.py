from aion.logs.normalize import app_frames, normalize_event, parse_python_frames, to_template

TRACE = '''Traceback (most recent call last):
  File "C:\\venv\\Lib\\site-packages\\starlette\\routing.py", line 70, in app
    response = await func(request)
  File "D:\\work\\orders-service\\app\\main.py", line 79, in order_total
    return pricing.compute_total(order, coupon)
  File "D:\\work\\orders-service\\app\\pricing.py", line 17, in apply_discount
    discount = subtotal * coupon["percent"] / 100
TypeError: 'NoneType' object is not subscriptable
'''


def test_template_masks_variable_parts():
    assert to_template("GET /orders/1042/total -> 500 in 3.2ms") == "GET /orders/<NUM>/total -> <NUM> in <NUM>ms"
    assert to_template("user 3f2b8c1e-1111-2222-3333-444455556666 from 10.0.0.12:443") == "user <UUID> from <IP>"


def test_same_error_different_values_share_signature():
    a = normalize_event({"level": "INFO", "message": "GET /orders/1001 -> 200"})
    b = normalize_event({"level": "INFO", "message": "GET /orders/1007 -> 200"})
    assert a.signature == b.signature


def test_different_exceptions_get_different_signatures():
    base = {"level": "ERROR", "message": "Unhandled exception", "exception": {"stacktrace": TRACE}}
    a = normalize_event({**base, "exception": {**base["exception"], "type": "TypeError", "message": "x"}})
    b = normalize_event({**base, "exception": {**base["exception"], "type": "KeyError", "message": "x"}})
    assert a.signature != b.signature


def test_frames_parsed_and_library_frames_filtered():
    frames = parse_python_frames(TRACE)
    assert [f["function"] for f in frames] == ["app", "order_total", "apply_discount"]
    assert [f["function"] for f in app_frames(frames)] == ["order_total", "apply_discount"]
    assert frames[-1]["line"] == 17


def test_level_normalised_and_request_kept():
    ev = normalize_event({"level": "warn", "message": "slow", "request": {"path": "/x", "status": 200},
                          "timestamp": "2026-10-04T10:00:00.000Z"})
    assert ev.level == "WARNING"
    assert ev.request == {"path": "/x", "status": 200}
    assert ev.timestamp.tzinfo is None and ev.timestamp.hour == 10


def test_compact_stack_trace_keeps_app_frames_only():
    from aion.ai.context import compact_stack_trace

    out = compact_stack_trace(TRACE)
    assert "site-packages" not in out
    assert "1 framework/library frame(s) omitted" in out
    assert 'discount = subtotal * coupon["percent"] / 100' in out
    assert out.strip().endswith("TypeError: 'NoneType' object is not subscriptable")
