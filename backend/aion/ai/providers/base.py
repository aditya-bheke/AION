"""Provider-neutral LLM interface.

AION never calls a vendor SDK directly from its business logic. RCA and patch
generation call `generate_structured(provider, system, user, OutputModel)`,
and any class implementing `LLMProvider.complete_json()` can be plugged in.
Swapping Claude for a local model is a configuration change, not a code change.
"""
from __future__ import annotations

import copy
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError


class LLMError(RuntimeError):
    """Raised when the model cannot produce a usable answer (network, refusal, invalid JSON...)."""


@dataclass
class LLMResponse:
    text: str
    usage: dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str  # e.g. "anthropic:claude-opus-5-5"

    def complete_json(self, system: str, user: str, schema: dict[str, Any], schema_name: str,
                      max_tokens: int) -> LLMResponse:
        """Return the model's reply, constrained (where supported) to `schema`."""
        ...


T = TypeVar("T", bound=BaseModel)


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic schema -> self-contained strict JSON schema.

    Inlines `$defs` references, marks every property required and forbids
    extra properties - the subset that structured-output decoders accept.
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            out = {k: resolve(v) for k, v in node.items() if k not in ("title", "default")}
            if out.get("type") == "object" and "properties" in out:
                out["required"] = list(out["properties"].keys())
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply, tolerating markdown fences or surrounding prose."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


@dataclass
class StructuredResult:
    output: Any
    raw_text: str
    usage: dict[str, Any]
    latency_ms: int
    attempts: int


def generate_structured(provider: LLMProvider, system: str, user: str, output_model: type[T],
                        max_tokens: int = 16000, max_attempts: int = 2) -> StructuredResult:
    """Call the model and validate its JSON against `output_model`.

    If the reply is not valid JSON or fails schema validation, the error is fed
    back to the model once ("repair" turn). Anything still invalid raises
    LLMError - AION never silently accepts malformed AI output.
    """
    schema = strict_json_schema(output_model)
    prompt = user
    last_error = ""
    usage_total: dict[str, Any] = {}
    started = time.monotonic()
    for attempt in range(1, max_attempts + 1):
        resp = provider.complete_json(system, prompt, schema, output_model.__name__, max_tokens)
        for k, v in resp.usage.items():
            if isinstance(v, (int, float)):
                usage_total[k] = usage_total.get(k, 0) + v
        try:
            parsed = output_model.model_validate(extract_json(resp.text))
            return StructuredResult(parsed, resp.text, usage_total,
                                    int((time.monotonic() - started) * 1000), attempt)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)[:2000]
            prompt = (
                f"{user}\n\n---\nYour previous reply could not be used because it was not valid "
                f"JSON for the required schema. Error:\n{last_error}\n\nReply again with ONLY a JSON "
                f"object that matches the schema."
            )
    raise LLMError(f"Model output failed validation after {max_attempts} attempts: {last_error}")
