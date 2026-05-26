"""Engine Protocols.

The harness treats both engines as black boxes. Only the Adapter
(see `archway_benchmarks.benchmarks.base.AnalysisResultAdapter`) is
permitted to know the structure of `Translation` or `AnalysisResult`.
"""
from __future__ import annotations

from typing import Any, Protocol

Translation = Any
AnalysisResult = Any


class TranslationEngine(Protocol):
    name: str

    def translate(self, source: str, path: str) -> Translation: ...


class AnalysisEngine(Protocol):
    name: str

    def analyze(self, translation: Translation) -> AnalysisResult: ...
