import pytest

from aion.ai.rca import ObservedEvidence, RCAOutput, RCAResult, Inference, ground
from aion.lifecycle import ALLOWED_TRANSITIONS, Status, can_transition


def test_no_path_to_deployment_without_approval():
    # The only state that can move to DEPLOYING is APPROVED.
    sources = [s for s, targets in ALLOWED_TRANSITIONS.items() if Status.DEPLOYING in targets]
    assert sources == [Status.APPROVED]
    assert not can_transition("awaiting_approval", Status.DEPLOYING)
    assert not can_transition("validating", Status.APPROVED)


@pytest.mark.parametrize("terminal", [Status.RESOLVED, Status.REJECTED])
def test_terminal_states(terminal):
    assert ALLOWED_TRANSITIONS[terminal] == set()


PACK = {
    "incident": {"service": "orders-service", "title": "TypeError"},
    "evidence": [
        {"id": "LOG-1", "kind": "log_cluster"},
        {"id": "TRACE-1", "kind": "stack_trace"},
        {"id": "COMMIT-69cfda3", "kind": "commit", "sha": "69cfda3aaaabbbbccccddddeeeeffff000011112"},
        {"id": "COMMIT-028dadd", "kind": "commit", "sha": "028dadd0000111122223333444455556666777788"},
    ],
}


def _rca(**overrides):
    base = dict(
        probable_root_cause="x", affected_service="orders-service", confidence=0.95,
        confidence_rationale="", remediation="", alternative_hypotheses=[],
        observed_evidence=[ObservedEvidence(evidence_id="TRACE-1", observation="TypeError at pricing.py:17")],
        inferences=[Inference(statement="commit broke it", based_on=["COMMIT-69cfda3"])],
        affected_files=["app/pricing.py"], suspected_commit="69cfda3",
    )
    base.update(overrides)
    return RCAResult(RCAOutput(**base), "test", None, {})


def test_grounding_accepts_valid_claims_and_expands_sha():
    r = ground(_rca(), PACK, {"app/pricing.py"})
    assert r.warnings == []
    assert r.output.suspected_commit == PACK["evidence"][2]["sha"]
    assert r.output.confidence == 0.95


def test_grounding_removes_hallucinations_and_caps_confidence():
    r = ground(_rca(
        observed_evidence=[ObservedEvidence(evidence_id="LOG-99", observation="made up")],
        affected_files=["app/pricing.py", "app/does_not_exist.py"],
        suspected_commit="deadbeef",
    ), PACK, {"app/pricing.py"})
    assert r.output.observed_evidence == []
    assert r.output.affected_files == ["app/pricing.py"]
    assert r.output.suspected_commit == ""
    assert r.output.confidence <= 0.3
    assert len(r.warnings) >= 3
