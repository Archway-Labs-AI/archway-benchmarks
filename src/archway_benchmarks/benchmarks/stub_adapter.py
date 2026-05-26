"""Adapter for `StubAnalysisResult` -> `list[Annotation]`.

This adapter is the only thing in the harness allowed to know the stub
result's shape. Kept in the benchmarks package because adapters are
benchmark-specific in general, but the stub is benchmark-agnostic because
the stub already returns harness-native `Annotation` objects.
"""
from __future__ import annotations

from archway_benchmarks.benchmarks.base import AnalysisResultAdapter
from archway_benchmarks.engines.stubs import StubAnalysisResult
from archway_benchmarks.types import Annotation, Snippet


class StubAnalysisResultAdapter(AnalysisResultAdapter):
    def to_annotations(
        self, result: StubAnalysisResult, snippet: Snippet
    ) -> list[Annotation]:
        return list(result.annotations_by_path.get(snippet.file_path, []))
