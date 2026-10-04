import json

import pytest

from aion.ai.providers.base import LLMError, LLMResponse, extract_json, generate_structured, strict_json_schema
from aion.ai.rca import RCAOutput


class Scripted:
    """Test double: returns pre-written replies in order."""

    name = "scripted:test"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete_json(self, system, user, schema, schema_name, max_tokens):
        self.prompts.append(user)
        return LLMResponse(self.replies.pop(0), {"input_tokens": 10, "output_tokens": 5})


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_strict_schema_is_self_contained():
    schema = strict_json_schema(RCAOutput)
    for node in _walk(schema):
        assert "$ref" not in node
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here you go: {"a": 2} hope it helps') == {"a": 2}


VALID = {
    "probable_root_cause": "r", "observed_evidence": [], "inferences": [], "affected_service": "s",
    "affected_files": [], "suspected_commit": "", "confidence": 0.5, "confidence_rationale": "",
    "remediation": "", "alternative_hypotheses": [],
}


def test_invalid_output_gets_one_repair_turn():
    p = Scripted(["not json at all", json.dumps(VALID)])
    result = generate_structured(p, "sys", "user", RCAOutput)
    assert result.attempts == 2
    assert "could not be used" in p.prompts[1]
    assert result.usage["input_tokens"] == 20


def test_persistently_invalid_output_raises():
    p = Scripted(['{"probable_root_cause": 1}', '{"still": "wrong"}'])
    with pytest.raises(LLMError):
        generate_structured(p, "sys", "user", RCAOutput)
