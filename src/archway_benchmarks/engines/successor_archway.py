"""Diagram-only TypeEvalPy bridge for the successor hybrid session."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
from typing import Any

from archway_benchmarks.benchmarks.base import AnalysisResultAdapter
from archway_benchmarks.engines.archway import ArchwayTranslation
from archway_benchmarks.types import Annotation, Location, Snippet


@dataclass(frozen=True)
class SuccessorGap:
    location: Location
    classification: str
    benchmark_case: str = ""
    expected_types: frozenset[str] = frozenset()
    address_ids: tuple[str, ...] = ()
    detail: str = ""


@dataclass
class SuccessorArchwayResult:
    source: str
    path: str
    session: Any | None = None
    forward: Any | None = None
    gaps: list[SuccessorGap] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class SuccessorGapAudit:
    snippets: int
    annotations: int
    predictions: int
    exact: int
    classifications: dict[str, int]
    groups: dict[str, int]
    representatives: dict[str, str]
    forward_events: int
    knowledge_deltas: int
    resolved_facts: int

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "snippets": self.snippets,
            "annotations": self.annotations,
            "predictions": self.predictions,
            "exact": self.exact,
            "classifications": self.classifications,
            "groups": self.groups,
            "representatives": self.representatives,
            "forward_events": self.forward_events,
            "knowledge_deltas": self.knowledge_deltas,
            "resolved_facts": self.resolved_facts,
        }


class SuccessorArchwayAnalysisEngine:
    """Translate once and run one type-prioritized forward session."""

    name = "archway-successor-analysis"

    def analyze(self, translation: Any) -> SuccessorArchwayResult:
        if not isinstance(translation, ArchwayTranslation):
            raise TypeError(
                "SuccessorArchwayAnalysisEngine consumes ArchwayTranslation"
            )
        try:
            from sd_core.analysis.diagram_analysis import (
                open_hybrid_forward_session,
            )
            from sd_core.tooling.harness import TranslationResult

            morphism = TranslationResult.from_source(
                translation.source, name="main"
            ).morphism
            session = open_hybrid_forward_session(morphism)
            forward = session.run_forward()
            return SuccessorArchwayResult(
                translation.source,
                translation.path,
                session=session,
                forward=forward,
            )
        except Exception as exc:
            return SuccessorArchwayResult(
                translation.source,
                translation.path,
                error=f"{type(exc).__name__}: {exc}",
            )


class SuccessorTypeEvalPyAdapter(AnalysisResultAdapter):
    """Read forward facts; classify unsupported observations explicitly."""

    def to_annotations(
        self, result: Any, snippet: Snippet
    ) -> list[Annotation]:
        if not isinstance(result, SuccessorArchwayResult):
            raise TypeError(
                "SuccessorTypeEvalPyAdapter requires SuccessorArchwayResult"
            )
        if result.error or result.session is None:
            return []
        predictions: list[Annotation] = []
        observations = result.session.type_observations()
        for requested in snippet.annotations:
            candidates = _map_observations(observations, requested.location)
            if not candidates:
                result.gaps.append(SuccessorGap(
                    requested.location,
                    "provenance_unmapped",
                    snippet.suite_path,
                    requested.types,
                    detail="no diagram type observation at benchmark location",
                ))
                continue
            resolved = [
                result.session.store.resolved(item.address)
                for item in candidates
            ]
            values = frozenset(
                _typeeval_name(value)
                for fact in resolved if fact is not None
                for value in fact.value
            )
            if values:
                predictions.append(Annotation(requested.location, values))
                continue
            result.gaps.append(SuccessorGap(
                requested.location,
                "mapped_open",
                snippet.suite_path,
                requested.types,
                tuple(item.address.id for item in candidates),
                "forward session emitted no usable type contribution",
            ))
        return predictions


def _map_observations(observations, location: Location):
    if location.kind != "variable" or location.function is not None:
        return ()
    exact = tuple(
        item for item in observations
        if item.name == location.name
        and item.position is not None
        and item.position.row == location.line
        and (
            location.col is None
            or item.position.col + 1 == location.col
        )
    )
    if exact:
        return exact
    return tuple(
        item for item in observations
        if item.name == location.name
        and item.position is not None
        and item.position.row == location.line
    )


def _typeeval_name(value: str) -> str:
    if value == "builtins.callable":
        return "callable"
    return value.removeprefix("builtins.")


def audit_successor_typeevalpy(
    benchmark,
    *,
    limit: int | None = None,
) -> SuccessorGapAudit:
    """Run a read-only gap census with one forward session per snippet."""

    from archway_benchmarks.engines.archway import ArchwayTranslationEngine

    translator = ArchwayTranslationEngine()
    analyzer = SuccessorArchwayAnalysisEngine()
    adapter = SuccessorTypeEvalPyAdapter()
    snippets = benchmark.load()
    if limit is not None:
        snippets = snippets[:limit]
    predictions: dict[Location, frozenset[str]] = {}
    classifications: Counter[str] = Counter()
    groups: Counter[str] = Counter()
    representatives: dict[str, str] = {}
    forward_events = knowledge_deltas = resolved_facts = 0
    for snippet in snippets:
        result = analyzer.analyze(
            translator.translate(snippet.source, snippet.file_path)
        )
        if result.error:
            for requested in snippet.annotations:
                gap = SuccessorGap(
                    requested.location,
                    "analysis_error",
                    snippet.suite_path,
                    requested.types,
                    detail=result.error,
                )
                result.gaps.append(gap)
        else:
            for prediction in adapter.to_annotations(result, snippet):
                predictions[prediction.location] = prediction.types
            assert result.forward is not None and result.session is not None
            forward_events += len(result.forward.events)
            knowledge_deltas += len(result.forward.knowledge_deltas)
            resolved_facts += len(
                result.session.store.snapshot().resolved_facts
            )
        category = snippet.suite_path.split("/", 1)[0]
        for gap in result.gaps:
            classifications[gap.classification] += 1
            key = f"{gap.classification}|{category}|{gap.location.kind}"
            groups[key] += 1
            representatives.setdefault(key, snippet.suite_path)
    ground_truth = {
        item.location: item.types
        for snippet in snippets for item in snippet.annotations
    }
    exact = sum(
        predictions.get(location) == expected
        for location, expected in ground_truth.items()
    )
    return SuccessorGapAudit(
        snippets=len(snippets),
        annotations=len(ground_truth),
        predictions=len(predictions),
        exact=exact,
        classifications=dict(sorted(classifications.items())),
        groups=dict(sorted(groups.items())),
        representatives=dict(sorted(representatives.items())),
        forward_events=forward_events,
        knowledge_deltas=knowledge_deltas,
        resolved_facts=resolved_facts,
    )
