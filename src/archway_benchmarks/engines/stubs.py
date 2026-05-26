"""Stub engines.

`StubTranslationEngine` returns a trivial placeholder.

`StubAnalysisEngine` is the workhorse: it perturbs ground-truth annotations at
a tunable accuracy `p` and emits an `AnalysisResult` whose shape is fully
opaque to the rest of the harness (only `StubAnalysisResultAdapter` knows it).

The stub takes ground truth as a hidden constructor input. This is a stub-only
shortcut; the runner enforces that real engines never have access to ground
truth, by constructing the stub adapter pair only via `make_stub_pair()`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from archway_benchmarks.types import Annotation, Location

# Pool of plausible-but-wrong type strings for perturbations.
_NOISE_POOL: tuple[str, ...] = (
    "int", "str", "float", "bool", "list", "dict", "tuple", "set",
    "bytes", "nonetype", "callable", "any", "object",
)


@dataclass(frozen=True)
class StubTranslation:
    """Opaque placeholder produced by StubTranslationEngine."""

    path: str
    source: str


@dataclass
class StubAnalysisResult:
    """Opaque-by-convention. Only StubAnalysisResultAdapter reads this."""

    annotations_by_path: dict[str, list[Annotation]] = field(default_factory=dict)


class StubTranslationEngine:
    name = "stub-translation"

    def translate(self, source: str, path: str) -> StubTranslation:
        return StubTranslation(path=path, source=source)


class StubAnalysisEngine:
    """Emits annotations derived from ground truth, perturbed at accuracy `p`.

    Hidden inputs:
      - `_ground_truth`: dict[Location, frozenset[str]] — wired in by
        `make_stub_pair()` only. Never expose to a real engine.

    With probability `p` we return the correct type-set; with probability
    `1 - p` we return a wrong but plausible type-set. The runner sets
    `--stub-accuracy` to control `p`.
    """

    name = "stub-analysis"

    def __init__(self, accuracy: float, seed: int | None = None) -> None:
        if not 0.0 <= accuracy <= 1.0:
            raise ValueError(f"accuracy must be in [0, 1], got {accuracy}")
        self.accuracy = accuracy
        self._rng = random.Random(seed)
        # `_ground_truth` and `_path_to_locations` are wired by make_stub_pair.
        self._ground_truth: dict[Location, frozenset[str]] = {}
        self._path_to_locations: dict[str, list[Location]] = {}

    def _wire_ground_truth(
        self,
        ground_truth: dict[Location, frozenset[str]],
        path_to_locations: dict[str, list[Location]],
    ) -> None:
        self._ground_truth = ground_truth
        self._path_to_locations = path_to_locations

    def analyze(self, translation: Any) -> StubAnalysisResult:
        if not isinstance(translation, StubTranslation):
            raise TypeError(
                "StubAnalysisEngine only consumes StubTranslation; got "
                f"{type(translation).__name__}"
            )

        annotations: list[Annotation] = []
        for loc in self._path_to_locations.get(translation.path, []):
            gt = self._ground_truth[loc]
            if self._rng.random() < self.accuracy:
                predicted = gt
            else:
                predicted = self._wrong_types_for(gt)
            annotations.append(Annotation(location=loc, types=predicted))

        return StubAnalysisResult(annotations_by_path={translation.path: annotations})

    def _wrong_types_for(self, gt: frozenset[str]) -> frozenset[str]:
        choices = [t for t in _NOISE_POOL if t not in gt]
        if not choices:
            return frozenset({"object"})
        return frozenset({self._rng.choice(choices)})


def make_stub_pair(
    snippets: "list[Any]",
    accuracy: float,
    seed: int | None = None,
) -> tuple[StubTranslationEngine, StubAnalysisEngine, "StubAnalysisResultAdapter"]:
    """Construct the stub trio with ground truth pre-wired.

    This is the ONLY supported way to use the stubs. The wiring step is
    quarantined here so real engine paths never touch ground truth.
    """
    from archway_benchmarks.benchmarks.stub_adapter import StubAnalysisResultAdapter

    ground_truth: dict[Location, frozenset[str]] = {}
    path_to_locations: dict[str, list[Location]] = {}
    for snip in snippets:
        for ann in snip.annotations:
            ground_truth[ann.location] = ann.types
            path_to_locations.setdefault(snip.file_path, []).append(ann.location)

    translation_engine = StubTranslationEngine()
    analysis_engine = StubAnalysisEngine(accuracy=accuracy, seed=seed)
    analysis_engine._wire_ground_truth(ground_truth, path_to_locations)
    return translation_engine, analysis_engine, StubAnalysisResultAdapter()
