"""Public contracts for paired BugsInPy agent-identification experiments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from .bugsinpy_protocol import (
    ProtocolViolation,
    RankedPredictionBundle,
    _reject_forbidden_fields,
)


AGENT_PAIR_SCHEMA = "archway.bugsinpy.agent-pair.v1"
CAUSAL_INTERACTION_SCHEMA = "archway.bugsinpy.agent-causal-interaction.v1"
AgentCondition = Literal["baseline", "archway-evidence"]
EvidenceDisposition = Literal["useful", "irrelevant", "misleading", "unusable"]
_CONDITIONS = frozenset({"baseline", "archway-evidence"})


def _require_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ProtocolViolation(f"{label} fields do not match the v1 schema")


@dataclass(frozen=True, slots=True)
class AgentUsage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0

    def __post_init__(self) -> None:
        if min(self.input_tokens, self.output_tokens, self.cached_input_tokens) < 0:
            raise ProtocolViolation("agent token counts cannot be negative")
        if self.cached_input_tokens > self.input_tokens:
            raise ProtocolViolation("cached input tokens cannot exceed input tokens")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_json(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "AgentUsage":
        _require_fields(
            value, {"input_tokens", "output_tokens", "cached_input_tokens"},
            "agent usage",
        )
        return cls(**value)


@dataclass(frozen=True, slots=True)
class EvidenceQueryRecord:
    sequence: int
    kind: str
    request: Mapping[str, Any]
    response_status: str
    duration_seconds: float
    response_sha256: str

    def __post_init__(self) -> None:
        if self.sequence < 1 or not self.kind or not self.response_status:
            raise ProtocolViolation("evidence query identity fields are invalid")
        if self.duration_seconds < 0:
            raise ProtocolViolation("evidence query duration cannot be negative")
        if len(self.response_sha256) != 64:
            raise ProtocolViolation("evidence response must have a sha256 identity")
        _reject_forbidden_fields(self.request)

    def to_json(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "request": dict(self.request),
            "response_status": self.response_status,
            "duration_seconds": self.duration_seconds,
            "response_sha256": self.response_sha256,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "EvidenceQueryRecord":
        _require_fields(value, {
            "sequence", "kind", "request", "response_status",
            "duration_seconds", "response_sha256",
        }, "evidence query")
        if not isinstance(value["request"], Mapping):
            raise ProtocolViolation("evidence query request must be an object")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class AgentTrial:
    trial_id: str
    pair_id: str
    condition: AgentCondition
    invocation_id: str
    model_id: str
    model_config: Mapping[str, Any]
    detector_input_sha256: str
    prediction: RankedPredictionBundle
    diagnosis: str
    duration_seconds: float
    usage: AgentUsage
    queries: tuple[EvidenceQueryRecord, ...] = ()

    def __post_init__(self) -> None:
        if self.condition not in _CONDITIONS:
            raise ProtocolViolation(f"unknown agent condition: {self.condition}")
        for name, value in (
            ("trial_id", self.trial_id),
            ("pair_id", self.pair_id),
            ("invocation_id", self.invocation_id),
            ("model_id", self.model_id),
            ("diagnosis", self.diagnosis),
        ):
            if not isinstance(value, str) or not value:
                raise ProtocolViolation(f"agent trial {name} must be non-empty")
        if len(self.detector_input_sha256) != 64:
            raise ProtocolViolation("agent trial must bind the detector input sha256")
        if self.duration_seconds < 0:
            raise ProtocolViolation("agent trial duration cannot be negative")
        sequences = [item.sequence for item in self.queries]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ProtocolViolation("evidence query sequences must be contiguous from one")
        if self.condition == "baseline" and self.queries:
            raise ProtocolViolation("baseline trial cannot contain Archway evidence queries")
        _reject_forbidden_fields(self.model_config)

    def to_json(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "pair_id": self.pair_id,
            "condition": self.condition,
            "invocation_id": self.invocation_id,
            "model_id": self.model_id,
            "model_config": dict(self.model_config),
            "detector_input_sha256": self.detector_input_sha256,
            "prediction": self.prediction.to_json(),
            "diagnosis": self.diagnosis,
            "duration_seconds": self.duration_seconds,
            "usage": self.usage.to_json(),
            "queries": [item.to_json() for item in self.queries],
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "AgentTrial":
        _require_fields(value, {
            "trial_id", "pair_id", "condition", "invocation_id", "model_id",
            "model_config", "detector_input_sha256", "prediction", "diagnosis",
            "duration_seconds", "usage", "queries",
        }, "agent trial")
        if not isinstance(value["model_config"], Mapping):
            raise ProtocolViolation("agent model_config must be an object")
        if not isinstance(value["prediction"], Mapping):
            raise ProtocolViolation("agent prediction must be an object")
        if not isinstance(value["usage"], Mapping):
            raise ProtocolViolation("agent usage must be an object")
        if not isinstance(value["queries"], list):
            raise ProtocolViolation("agent queries must be a list")
        return cls(
            trial_id=value["trial_id"],
            pair_id=value["pair_id"],
            condition=value["condition"],
            invocation_id=value["invocation_id"],
            model_id=value["model_id"],
            model_config=value["model_config"],
            detector_input_sha256=value["detector_input_sha256"],
            prediction=RankedPredictionBundle.from_json(value["prediction"]),
            diagnosis=value["diagnosis"],
            duration_seconds=value["duration_seconds"],
            usage=AgentUsage.from_json(value["usage"]),
            queries=tuple(EvidenceQueryRecord.from_json(item) for item in value["queries"]),
        )


@dataclass(frozen=True, slots=True)
class AgentPair:
    pair_id: str
    baseline: AgentTrial
    archway_evidence: AgentTrial
    schema: str = AGENT_PAIR_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != AGENT_PAIR_SCHEMA or not self.pair_id:
            raise ProtocolViolation("invalid agent pair identity")
        if self.baseline.condition != "baseline":
            raise ProtocolViolation("agent pair baseline arm has the wrong condition")
        if self.archway_evidence.condition != "archway-evidence":
            raise ProtocolViolation("agent pair evidence arm has the wrong condition")
        if {self.baseline.pair_id, self.archway_evidence.pair_id} != {self.pair_id}:
            raise ProtocolViolation("agent trial pair identity mismatch")
        if self.baseline.invocation_id == self.archway_evidence.invocation_id:
            raise ProtocolViolation("paired arms require independent invocation contexts")
        equal_fields = (
            ("model_id", self.baseline.model_id, self.archway_evidence.model_id),
            ("model_config", dict(self.baseline.model_config), dict(self.archway_evidence.model_config)),
            (
                "detector_input_sha256",
                self.baseline.detector_input_sha256,
                self.archway_evidence.detector_input_sha256,
            ),
            ("bug_key", self.baseline.prediction.bug_key, self.archway_evidence.prediction.bug_key),
            (
                "buggy_revision",
                self.baseline.prediction.buggy_revision,
                self.archway_evidence.prediction.buggy_revision,
            ),
            (
                "protocol",
                self.baseline.prediction.protocol,
                self.archway_evidence.prediction.protocol,
            ),
            (
                "repository coverage",
                (
                    self.baseline.prediction.repository_files,
                    self.baseline.prediction.repository_loc,
                    self.baseline.prediction.analyzed_files,
                    self.baseline.prediction.analyzed_loc,
                ),
                (
                    self.archway_evidence.prediction.repository_files,
                    self.archway_evidence.prediction.repository_loc,
                    self.archway_evidence.prediction.analyzed_files,
                    self.archway_evidence.prediction.analyzed_loc,
                ),
            ),
        )
        for name, left, right in equal_fields:
            if left != right:
                raise ProtocolViolation(f"paired arms differ in {name}")

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "pair_id": self.pair_id,
            "baseline": self.baseline.to_json(),
            "archway_evidence": self.archway_evidence.to_json(),
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "AgentPair":
        _require_fields(
            value, {"schema", "pair_id", "baseline", "archway_evidence"},
            "agent pair",
        )
        if not isinstance(value["baseline"], Mapping) or not isinstance(
            value["archway_evidence"], Mapping
        ):
            raise ProtocolViolation("agent pair arms must be objects")
        return cls(
            schema=value["schema"],
            pair_id=value["pair_id"],
            baseline=AgentTrial.from_json(value["baseline"]),
            archway_evidence=AgentTrial.from_json(value["archway_evidence"]),
        )


@dataclass(frozen=True, slots=True)
class EvidenceAdjudication:
    pair_id: str
    query_sequence: int
    disposition: EvidenceDisposition
    rationale: str

    def __post_init__(self) -> None:
        if not self.pair_id or self.query_sequence < 1 or not self.rationale:
            raise ProtocolViolation("invalid evidence adjudication identity")
        if self.disposition not in {"useful", "irrelevant", "misleading", "unusable"}:
            raise ProtocolViolation("invalid evidence disposition")

    def to_json(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "query_sequence": self.query_sequence,
            "disposition": self.disposition,
            "rationale": self.rationale,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "EvidenceAdjudication":
        _require_fields(
            value, {"pair_id", "query_sequence", "disposition", "rationale"},
            "evidence adjudication",
        )
        return cls(**value)


@dataclass(frozen=True, slots=True)
class CausalStage:
    invocation_id: str
    prediction: RankedPredictionBundle
    diagnosis: str
    duration_seconds: float
    usage: AgentUsage

    def __post_init__(self) -> None:
        if not self.invocation_id or not self.diagnosis or self.duration_seconds < 0:
            raise ProtocolViolation("invalid causal stage identity or metrics")

    def to_json(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "prediction": self.prediction.to_json(),
            "diagnosis": self.diagnosis,
            "duration_seconds": self.duration_seconds,
            "usage": self.usage.to_json(),
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "CausalStage":
        _require_fields(
            value, {"invocation_id", "prediction", "diagnosis", "duration_seconds", "usage"},
            "causal stage",
        )
        return cls(
            invocation_id=value["invocation_id"],
            prediction=RankedPredictionBundle.from_json(value["prediction"]),
            diagnosis=value["diagnosis"],
            duration_seconds=value["duration_seconds"],
            usage=AgentUsage.from_json(value["usage"]),
        )


@dataclass(frozen=True, slots=True)
class CausalEvidenceInteraction:
    interaction_id: str
    model_id: str
    model_config: Mapping[str, Any]
    detector_input_sha256: str
    proposal: CausalStage
    review: CausalStage
    query: EvidenceQueryRecord
    hypothesis_before: str
    hypothesis_after: str
    evidence_impact: str
    evidence_cited_in_diagnosis: bool
    evidence_disposition: EvidenceDisposition
    adjudication_rationale: str
    schema: str = CAUSAL_INTERACTION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CAUSAL_INTERACTION_SCHEMA or not self.interaction_id:
            raise ProtocolViolation("invalid causal interaction identity")
        if not self.model_id or len(self.detector_input_sha256) != 64:
            raise ProtocolViolation("causal interaction lacks pinned model or input identity")
        if self.proposal.invocation_id == self.review.invocation_id:
            raise ProtocolViolation("causal stages require independent invocation identities")
        for name in ("protocol", "bug_key", "buggy_revision"):
            if getattr(self.proposal.prediction, name) != getattr(self.review.prediction, name):
                raise ProtocolViolation(f"causal stage predictions differ in {name}")
        if not self.hypothesis_before or not self.hypothesis_after:
            raise ProtocolViolation("causal interaction requires before/after hypotheses")
        if self.evidence_impact not in {"confirmed", "contradicted", "reranked"}:
            raise ProtocolViolation("invalid causal evidence impact")
        if self.evidence_cited_in_diagnosis is not True:
            raise ProtocolViolation("causal review must cite the evidence disposition")
        if self.evidence_disposition not in {
            "useful", "irrelevant", "misleading", "unusable"
        } or not self.adjudication_rationale:
            raise ProtocolViolation("causal interaction requires evidence adjudication")
        _reject_forbidden_fields(self.model_config)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interaction_id": self.interaction_id,
            "model_id": self.model_id,
            "model_config": dict(self.model_config),
            "detector_input_sha256": self.detector_input_sha256,
            "proposal": self.proposal.to_json(),
            "review": self.review.to_json(),
            "query": self.query.to_json(),
            "hypothesis_before": self.hypothesis_before,
            "hypothesis_after": self.hypothesis_after,
            "evidence_impact": self.evidence_impact,
            "evidence_cited_in_diagnosis": self.evidence_cited_in_diagnosis,
            "evidence_disposition": self.evidence_disposition,
            "adjudication_rationale": self.adjudication_rationale,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "CausalEvidenceInteraction":
        _require_fields(value, {
            "schema", "interaction_id", "model_id", "model_config",
            "detector_input_sha256", "proposal", "review", "query",
            "hypothesis_before", "hypothesis_after", "evidence_impact",
            "evidence_cited_in_diagnosis", "evidence_disposition",
            "adjudication_rationale",
        }, "causal interaction")
        return cls(
            schema=value["schema"], interaction_id=value["interaction_id"],
            model_id=value["model_id"], model_config=value["model_config"],
            detector_input_sha256=value["detector_input_sha256"],
            proposal=CausalStage.from_json(value["proposal"]),
            review=CausalStage.from_json(value["review"]),
            query=EvidenceQueryRecord.from_json(value["query"]),
            hypothesis_before=value["hypothesis_before"],
            hypothesis_after=value["hypothesis_after"],
            evidence_impact=value["evidence_impact"],
            evidence_cited_in_diagnosis=value["evidence_cited_in_diagnosis"],
            evidence_disposition=value["evidence_disposition"],
            adjudication_rationale=value["adjudication_rationale"],
        )
