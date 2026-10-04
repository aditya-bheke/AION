"""Redaction of secrets and personal data before anything is sent to an LLM.

Logs and stack traces can contain customer e-mails, phone numbers, card
numbers, passwords and API tokens. When AION uses a hosted model, the prompt
leaves the machine, so AION masks these values first and records what it
masked (counts per kind) next to the evidence pack.

Two profiles:
* ``log``  - everything below; for log templates, error messages, request
             query strings, test output.
* ``code`` - only high-confidence secret formats (keys, tokens, JWTs). Source
             code is quoted back by the model in search/replace edits, so the
             broad PII heuristics would make edits fail to match.

Values are replaced with ``[REDACTED:<kind>]``. Git SHAs, line numbers and
order ids are deliberately not matched.
"""
from __future__ import annotations

import copy
import re
from collections import Counter
from typing import Any, Callable

# (kind, pattern, replacement) - replacement may use groups to keep a key name visible.
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "[REDACTED:private_key]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[REDACTED:jwt]"),
    ("bearer_token", re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{12,}"), r"\1 [REDACTED:token]"),
    ("api_key", re.compile(r"\b(?:sk-ant-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}"
                           r"|gh[pousr]_[A-Za-z0-9]{30,}|xox[abpr]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,})\b"),
     "[REDACTED:api_key]"),
]

_PII_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    # key=value / key: value secrets, e.g. "password=hunter2", "api_key: abc123" (key name kept)
    ("secret_value", re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token"
                                r"|client[_-]?secret)\b(\s*[=:]\s*)(['\"]?)[^\s'\"&,;]{3,}\3"), r"\1\2[REDACTED:secret]"),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED:email]"),
    ("phone", re.compile(r"(?<![\w-])(?:\+91[\s-]?)?[6-9]\d{9}(?![\w-])"), "[REDACTED:phone]"),
]

_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def _luhn_ok(number: str) -> bool:
    digits = [int(d) for d in number if d.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def redact_text(text: str, profile: str = "log", counts: Counter | None = None) -> str:
    """Mask secrets (and, for the log profile, personal data) in `text`."""
    if not text:
        return text
    counts = counts if counts is not None else Counter()
    patterns = _SECRET_PATTERNS + (_PII_PATTERNS if profile == "log" else [])
    for kind, pattern, replacement in patterns:
        text, n = pattern.subn(replacement, text)
        if n:
            counts[kind] += n
    if profile == "log":
        def card(m: re.Match) -> str:
            if _luhn_ok(m.group(0)):
                counts["card_number"] += 1
                return "[REDACTED:card_number]"
            return m.group(0)
        text = _CARD.sub(card, text)
    return text


# Which evidence fields are code (quoted back in edits) - everything else is log-like text.
_CODE_FIELDS = {"diff", "code", "fix_diff"}


def _walk(value: Any, key: str, fn: Callable[[str, str], str]) -> Any:
    if isinstance(value, str):
        return fn(value, "code" if key in _CODE_FIELDS else "log")
    if isinstance(value, list):
        return [_walk(v, key, fn) for v in value]
    if isinstance(value, dict):
        return {k: _walk(v, k, fn) for k, v in value.items()}
    return value


def redact_pack(pack: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Return a redacted copy of an evidence pack and the counts of what was masked."""
    counts: Counter = Counter()
    keep = {"analysed_revision"}  # git SHAs must stay intact
    redacted = {k: (copy.deepcopy(v) if k in keep else _walk(v, k, lambda t, p: redact_text(t, p, counts)))
                for k, v in pack.items()}
    return redacted, dict(counts)
