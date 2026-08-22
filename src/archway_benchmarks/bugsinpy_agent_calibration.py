"""Public oracle-side eligibility contract for BugsInPy evidence calibration.

This record is evaluator input, never detector input.  It permits deliberately
selected interface-calibration cases while making that selection bias explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from .bugsinpy_protocol import ProtocolViolation


CALIBRATION_ELIGIBILITY_SCHEMA = "archway.bugsinpy.agent-evidence-calibration-eligibility.v1"
EvidenceRelation = Literal["direct", "indirect", "unrelated"]
_RELATIONS = frozenset({"direct", "indirect", "unrelated"})


@dataclass(frozen=True, slots=True)
class CalibrationEligibility:
    """Post-probe, oracle-side judgment that must stay outside the agent cage."""

    bug_key: str
    buggy_revision: str
    corpus_revision: str
    probe_sha256: str
    oracle_patch_sha256: str
    evidence_relation: EvidenceRelation
    rationale: str
    calibration_only: bool
    detector_received_oracle: bool
    schema: str = CALIBRATION_ELIGIBILITY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CALIBRATION_ELIGIBILITY_SCHEMA:
            raise ProtocolViolation("unsupported calibration eligibility schema")
        for name, value in (
            ("bug_key", self.bug_key),
            ("buggy_revision", self.buggy_revision),
            ("corpus_revision", self.corpus_revision),
            ("rationale", self.rationale),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ProtocolViolation(f"calibration eligibility {name} must be non-empty")
        for name, value in (
            ("probe_sha256", self.probe_sha256),
            ("oracle_patch_sha256", self.oracle_patch_sha256),
        ):
            if not isinstance(value, str) or len(value) != 64:
                raise ProtocolViolation(f"calibration eligibility {name} must be a sha256")
        if self.evidence_relation not in _RELATIONS:
            raise ProtocolViolation("invalid evidence-to-benchmark relation")
        if self.calibration_only is not True:
            raise ProtocolViolation("oracle-selected evidence cases must be calibration-only")
        if self.detector_received_oracle is not False:
            raise ProtocolViolation("detector execution must not receive oracle eligibility data")

    @property
    def eligible(self) -> bool:
        return self.evidence_relation == "direct"

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "bug_key": self.bug_key,
            "buggy_revision": self.buggy_revision,
            "corpus_revision": self.corpus_revision,
            "probe_sha256": self.probe_sha256,
            "oracle_patch_sha256": self.oracle_patch_sha256,
            "evidence_relation": self.evidence_relation,
            "rationale": self.rationale,
            "calibration_only": self.calibration_only,
            "detector_received_oracle": self.detector_received_oracle,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "CalibrationEligibility":
        expected = {
            "schema", "bug_key", "buggy_revision", "corpus_revision",
            "probe_sha256", "oracle_patch_sha256", "evidence_relation",
            "rationale", "calibration_only", "detector_received_oracle",
        }
        if set(value) != expected:
            raise ProtocolViolation("calibration eligibility fields do not match v1 schema")
        return cls(**value)
