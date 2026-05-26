"""Benchmark + Adapter abstractions.

To add a new benchmark you implement two classes:
  1. A `Benchmark` subclass that loads snippets, exposes ground truth, and
     scores a `dict[Location, frozenset[str]]` against an oracle scorer.
  2. An `AnalysisResultAdapter` that translates the analysis engine's opaque
     output for that benchmark into `list[Annotation]`.

The harness never touches the engine's output shape except through an Adapter.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from archway_benchmarks.engines.base import AnalysisResult
from archway_benchmarks.types import Annotation, Location, Scores, Snippet


class AnalysisResultAdapter(ABC):
    """The ONLY place that knows the analysis engine's output shape.

    One concrete adapter per `(benchmark, engine_version)` pair. The adapter is
    responsible for projecting the opaque `AnalysisResult` onto the benchmark's
    `Location` space.
    """

    @abstractmethod
    def to_annotations(
        self, result: AnalysisResult, snippet: Snippet
    ) -> list[Annotation]: ...


class Benchmark(ABC):
    name: str

    @abstractmethod
    def load(self) -> list[Snippet]: ...

    @abstractmethod
    def ground_truth(self) -> dict[Location, frozenset[str]]: ...

    @abstractmethod
    def score(self, predictions: dict[Location, frozenset[str]]) -> Scores: ...

    @abstractmethod
    def to_tool_format(
        self, predictions: dict[Location, frozenset[str]]
    ) -> Any:
        """Emit predictions in the benchmark's native tool-output format.

        For Layer-A comparability: a real third-party tool runner can ingest
        this and our predictions are indistinguishable from any other tool's.
        """
        ...
