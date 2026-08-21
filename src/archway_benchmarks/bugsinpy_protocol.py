"""Claim-grade BugsInPy detector input and ranked prediction contracts.

Ground truth is deliberately absent from this module.  Corpus loaders and scorers may
know the fix patch; a detector process must be launched from ``DetectorInputManifest``
alone.  Strict field validation makes accidental additions visible instead of silently
turning hidden evaluator data into detector input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping


DETECTOR_INPUT_SCHEMA = "archway.bugsinpy.detector-input.v1"
PREDICTION_SCHEMA = "archway.bugsinpy.ranked-prediction.v1"

DetectionProtocol = Literal["repository-static-v1", "test-directed-static-v1"]

_PROTOCOLS = frozenset({"repository-static-v1", "test-directed-static-v1"})
_INPUT_FIELDS = frozenset(
    {"schema", "protocol", "bug_key", "project", "buggy_revision", "repository_root", "entrypoints"}
)
_PREDICTION_FIELDS = frozenset(
    {"schema", "protocol", "bug_key", "buggy_revision", "coverage", "findings"}
)
_FORBIDDEN_FIELD_TOKENS = (
    "patch",
    "fixed",
    "ground_truth",
    "ground-truth",
    "bug_location",
    "bug-location",
    "files_touched",
    "touched_files",
    "lines_changed",
    "bug_class",
)


class ProtocolViolation(ValueError):
    """A detector input or prediction violates the public benchmark contract."""


def _reject_forbidden_fields(value: object, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).lower()
            if any(token in key for token in _FORBIDDEN_FIELD_TOKENS):
                raise ProtocolViolation(f"forbidden detector-input field at {path}.{raw_key}")
            _reject_forbidden_fields(child, path=f"{path}.{raw_key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_forbidden_fields(child, path=f"{path}[{index}]")


@dataclass(frozen=True)
class DetectorInputManifest:
    """The complete information boundary visible to one detector execution."""

    protocol: DetectionProtocol
    bug_key: str
    project: str
    buggy_revision: str
    repository_root: str
    entrypoints: tuple[str, ...] = ()
    schema: str = DETECTOR_INPUT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != DETECTOR_INPUT_SCHEMA:
            raise ProtocolViolation(f"unsupported detector-input schema: {self.schema}")
        if self.protocol not in _PROTOCOLS:
            raise ProtocolViolation(f"unsupported detection protocol: {self.protocol}")
        for name, value in (
            ("bug_key", self.bug_key),
            ("project", self.project),
            ("buggy_revision", self.buggy_revision),
            ("repository_root", self.repository_root),
        ):
            if not value or not isinstance(value, str):
                raise ProtocolViolation(f"{name} must be a non-empty string")
        if self.protocol == "repository-static-v1" and self.entrypoints:
            raise ProtocolViolation("repository-static-v1 cannot receive test entrypoints")
        if self.protocol == "test-directed-static-v1" and not self.entrypoints:
            raise ProtocolViolation("test-directed-static-v1 requires at least one entrypoint")
        if any(not isinstance(item, str) or not item for item in self.entrypoints):
            raise ProtocolViolation("entrypoints must be non-empty strings")

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "protocol": self.protocol,
            "bug_key": self.bug_key,
            "project": self.project,
            "buggy_revision": self.buggy_revision,
            "repository_root": self.repository_root,
            "entrypoints": list(self.entrypoints),
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "DetectorInputManifest":
        _reject_forbidden_fields(value)
        unknown = set(value) - _INPUT_FIELDS
        if unknown:
            raise ProtocolViolation(f"unknown detector-input fields: {sorted(unknown)}")
        missing = _INPUT_FIELDS - set(value)
        if missing:
            raise ProtocolViolation(f"missing detector-input fields: {sorted(missing)}")
        entrypoints = value["entrypoints"]
        if not isinstance(entrypoints, list):
            raise ProtocolViolation("entrypoints must be a list")
        return cls(
            schema=value["schema"],
            protocol=value["protocol"],
            bug_key=value["bug_key"],
            project=value["project"],
            buggy_revision=value["buggy_revision"],
            repository_root=value["repository_root"],
            entrypoints=tuple(entrypoints),
        )


@dataclass(frozen=True)
class RankedFinding:
    """One detector-ranked source location, produced before ground-truth access."""

    rank: int
    file: str
    start_line: int
    end_line: int
    kind: str
    confidence: float | None = None
    evidence: tuple[dict[str, Any], ...] = ()
    reachability: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ProtocolViolation("finding rank must be positive")
        if not self.file or self.start_line < 1 or self.end_line < self.start_line:
            raise ProtocolViolation("finding must have a valid file and positive line span")
        if not self.kind:
            raise ProtocolViolation("finding kind must be non-empty")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ProtocolViolation("finding confidence must be between zero and one")

    def lines(self) -> frozenset[int]:
        return frozenset(range(self.start_line, self.end_line + 1))

    def to_json(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "file": self.file,
            "span": {"start_line": self.start_line, "end_line": self.end_line},
            "kind": self.kind,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "reachability": self.reachability,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "RankedFinding":
        expected = {"rank", "file", "span", "kind", "confidence", "evidence", "reachability"}
        if set(value) != expected:
            raise ProtocolViolation("ranked finding fields do not match the v1 schema")
        span = value["span"]
        if not isinstance(span, Mapping) or set(span) != {"start_line", "end_line"}:
            raise ProtocolViolation("finding span does not match the v1 schema")
        evidence = value["evidence"]
        reachability = value["reachability"]
        if not isinstance(evidence, list) or not all(isinstance(item, dict) for item in evidence):
            raise ProtocolViolation("finding evidence must be a list of objects")
        if not isinstance(reachability, dict):
            raise ProtocolViolation("finding reachability must be an object")
        return cls(
            rank=value["rank"],
            file=value["file"],
            start_line=span["start_line"],
            end_line=span["end_line"],
            kind=value["kind"],
            confidence=value["confidence"],
            evidence=tuple(evidence),
            reachability=reachability,
        )


@dataclass(frozen=True)
class RankedPredictionBundle:
    """Sealed detector output plus repository-wide analysis coverage."""

    protocol: DetectionProtocol
    bug_key: str
    buggy_revision: str
    findings: tuple[RankedFinding, ...]
    repository_files: int
    repository_loc: int
    analyzed_files: int
    analyzed_loc: int
    schema: str = PREDICTION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PREDICTION_SCHEMA:
            raise ProtocolViolation(f"unsupported prediction schema: {self.schema}")
        if self.protocol not in _PROTOCOLS:
            raise ProtocolViolation(f"unsupported detection protocol: {self.protocol}")
        if not self.bug_key or not self.buggy_revision:
            raise ProtocolViolation("prediction identity fields must be non-empty")
        if min(self.repository_files, self.repository_loc, self.analyzed_files, self.analyzed_loc) < 0:
            raise ProtocolViolation("coverage counts cannot be negative")
        if self.analyzed_files > self.repository_files or self.analyzed_loc > self.repository_loc:
            raise ProtocolViolation("analyzed coverage cannot exceed repository coverage")
        ranks = [item.rank for item in self.findings]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ProtocolViolation("finding ranks must be unique, ordered, and contiguous from one")
        locations = [(item.file, item.start_line, item.end_line) for item in self.findings]
        if len(locations) != len(set(locations)):
            raise ProtocolViolation("prediction cannot repeat the same source span")

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "protocol": self.protocol,
            "bug_key": self.bug_key,
            "buggy_revision": self.buggy_revision,
            "coverage": {
                "repository_files": self.repository_files,
                "repository_loc": self.repository_loc,
                "analyzed_files": self.analyzed_files,
                "analyzed_loc": self.analyzed_loc,
            },
            "findings": [item.to_json() for item in self.findings],
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "RankedPredictionBundle":
        _reject_forbidden_fields(value)
        if set(value) != _PREDICTION_FIELDS:
            raise ProtocolViolation("prediction fields do not match the v1 schema")
        coverage = value["coverage"]
        expected_coverage = {
            "repository_files", "repository_loc", "analyzed_files", "analyzed_loc"
        }
        if not isinstance(coverage, Mapping) or set(coverage) != expected_coverage:
            raise ProtocolViolation("prediction coverage does not match the v1 schema")
        findings = value["findings"]
        if not isinstance(findings, list) or not all(isinstance(item, Mapping) for item in findings):
            raise ProtocolViolation("prediction findings must be a list of objects")
        return cls(
            schema=value["schema"],
            protocol=value["protocol"],
            bug_key=value["bug_key"],
            buggy_revision=value["buggy_revision"],
            findings=tuple(RankedFinding.from_json(item) for item in findings),
            repository_files=coverage["repository_files"],
            repository_loc=coverage["repository_loc"],
            analyzed_files=coverage["analyzed_files"],
            analyzed_loc=coverage["analyzed_loc"],
        )
