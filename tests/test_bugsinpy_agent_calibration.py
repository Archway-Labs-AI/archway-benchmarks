from __future__ import annotations

import pytest

from archway_benchmarks.bugsinpy_agent_calibration import CalibrationEligibility
from archway_benchmarks.bugsinpy_protocol import ProtocolViolation


def _record(**updates):
    value = {
        "schema": "archway.bugsinpy.agent-evidence-calibration-eligibility.v1",
        "bug_key": "demo:1", "buggy_revision": "b" * 40,
        "corpus_revision": "c" * 40, "probe_sha256": "a" * 64,
        "oracle_patch_sha256": "d" * 64, "evidence_relation": "direct",
        "rationale": "The query observes the argument whose forwarding is changed by the fix.",
        "calibration_only": True, "detector_received_oracle": False,
    }
    value.update(updates)
    return value


def test_direct_oracle_isolated_record_is_eligible() -> None:
    record = CalibrationEligibility.from_json(_record())
    assert record.eligible
    assert record.to_json() == _record()


@pytest.mark.parametrize("relation", ["indirect", "unrelated"])
def test_non_direct_relation_is_ineligible(relation: str) -> None:
    assert not CalibrationEligibility.from_json(
        _record(evidence_relation=relation)
    ).eligible


def test_oracle_selected_record_cannot_claim_representativeness_or_leakage() -> None:
    with pytest.raises(ProtocolViolation, match="calibration-only"):
        CalibrationEligibility.from_json(_record(calibration_only=False))
    with pytest.raises(ProtocolViolation, match="must not receive oracle"):
        CalibrationEligibility.from_json(_record(detector_received_oracle=True))


def test_contract_is_strict() -> None:
    with pytest.raises(ProtocolViolation, match="fields do not match"):
        CalibrationEligibility.from_json({**_record(), "agent_prompt": "oracle"})
