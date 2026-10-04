"""Log normalisation, templating and fingerprinting.

The goal is deduplication: thousands of log lines that differ only in
variable values (order ids, durations, request ids...) should collapse into
one *template* and one *signature*.

    "Order 1042 total failed after 3.2ms"  ->  "Order <NUM> total failed after <NUM>ms"

For errors we also fingerprint the stack trace (exception type + the
innermost frames' file/function). Line numbers are deliberately excluded so
a signature stays stable when unrelated lines above it are edited.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# Order matters: more specific patterns must run before generic numbers.
_MASKS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<UUID>"),
    (re.compile(r"https?://[^\s\"']+"), "<URL>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "<EMAIL>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<IP>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<HEX>"),
    (re.compile(r"\b[0-9a-fA-F]{12,}\b"), "<HEX>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?"), "<TS>"),
    (re.compile(r"(?<![\w<])-?\d+(?:\.\d+)?"), "<NUM>"),
]
_WS = re.compile(r"\s+")
_FRAME_RE = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>[^\s]+)')
_ERROR_LEVELS = {"ERROR", "CRITICAL", "FATAL"}


def to_template(message: str) -> str:
    text = message
    for pattern, token in _MASKS:
        text = pattern.sub(token, text)
    return _WS.sub(" ", text).strip()


def parse_python_frames(stack_trace: str) -> list[dict[str, Any]]:
    """Extract (file, line, function) from a Python traceback, outermost first."""
    frames = []
    for m in _FRAME_RE.finditer(stack_trace or ""):
        frames.append({"file": m.group("file").replace("\\", "/"), "line": int(m.group("line")), "function": m.group("func")})
    return frames


def is_library_frame(path: str) -> bool:
    p = path.replace("\\", "/").lower()
    return "site-packages" in p or "/lib/python" in p or "dist-packages" in p or p.startswith("<")


def app_frames(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in frames if not is_library_frame(f["file"])]


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def compute_signature(level: str, logger: Optional[str], template: str, exception_type: Optional[str],
                      frames: list[dict[str, Any]]) -> str:
    parts = [level.upper(), logger or "", template, exception_type or ""]
    # Innermost three application frames identify *where* the error happens.
    for f in app_frames(frames)[-3:]:
        parts.append(f"{_basename(f['file'])}:{f['function']}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def parse_timestamp(value: Any) -> datetime:
    """Accept ISO-8601 strings or epoch seconds; return naive UTC."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
    if isinstance(value, str) and value:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class NormalizedEvent:
    timestamp: datetime
    level: str
    logger: Optional[str]
    message: str
    template: str
    signature: str
    exception_type: Optional[str] = None
    exception_message: Optional[str] = None
    stack_trace: Optional[str] = None
    frames: list[dict[str, Any]] = field(default_factory=list)
    request: Optional[dict[str, Any]] = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        return self.level in _ERROR_LEVELS


_KNOWN_KEYS = {"timestamp", "time", "ts", "level", "severity", "logger", "message", "msg", "exception", "request", "service"}


def normalize_event(raw: dict[str, Any]) -> NormalizedEvent:
    """Convert one structured (JSON) log record into AION's canonical form."""
    level = str(raw.get("level") or raw.get("severity") or "INFO").upper()
    if level == "WARN":
        level = "WARNING"
    message = str(raw.get("message") or raw.get("msg") or "")
    exc = raw.get("exception") or {}
    exc_type = exc.get("type") if isinstance(exc, dict) else None
    exc_msg = exc.get("message") if isinstance(exc, dict) else None
    stack = exc.get("stacktrace") if isinstance(exc, dict) else None
    frames = parse_python_frames(stack) if stack else []

    # The template includes the exception text so different errors raised by
    # the same "Unhandled exception" log call are not merged together.
    template_source = message if not exc_type else f"{message} | {exc_type}: {exc_msg or ''}"
    template = to_template(template_source)
    logger = raw.get("logger")
    signature = compute_signature(level, logger, template, exc_type, frames)
    return NormalizedEvent(
        timestamp=parse_timestamp(raw.get("timestamp") or raw.get("time") or raw.get("ts")),
        level=level,
        logger=logger,
        message=message,
        template=template,
        signature=signature,
        exception_type=exc_type,
        exception_message=exc_msg,
        stack_trace=stack,
        frames=frames,
        request=raw.get("request") if isinstance(raw.get("request"), dict) else None,
        attributes={k: v for k, v in raw.items() if k not in _KNOWN_KEYS},
    )
