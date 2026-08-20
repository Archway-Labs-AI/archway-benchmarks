"""Diagram-only TypeEvalPy bridge for the successor hybrid session."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
from pathlib import Path
import re
from typing import Any, Callable

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
    targeted_runs: list[Any] = field(default_factory=list)
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
    family_groups: dict[str, int]
    family_representatives: dict[str, str]
    forward_events: int
    knowledge_deltas: int
    resolved_facts: int
    targeted_roots: int
    targeted_cache_hits: int
    targeted_events: int
    targeted_knowledge_deltas: int
    targeted_topology_changes: int

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "snippets": self.snippets,
            "annotations": self.annotations,
            "predictions": self.predictions,
            "exact": self.exact,
            "classifications": self.classifications,
            "groups": self.groups,
            "representatives": self.representatives,
            "family_groups": self.family_groups,
            "family_representatives": self.family_representatives,
            "forward_events": self.forward_events,
            "knowledge_deltas": self.knowledge_deltas,
            "resolved_facts": self.resolved_facts,
            "targeted_roots": self.targeted_roots,
            "targeted_cache_hits": self.targeted_cache_hits,
            "targeted_events": self.targeted_events,
            "targeted_knowledge_deltas": self.targeted_knowledge_deltas,
            "targeted_topology_changes": self.targeted_topology_changes,
        }


class SuccessorArchwayAnalysisEngine:
    """Translate once and run one type-prioritized forward session."""

    name = "archway-successor-analysis"

    def __init__(self, *, record_events: bool = True) -> None:
        self.record_events = record_events

    def analyze(self, translation: Any) -> SuccessorArchwayResult:
        if not isinstance(translation, ArchwayTranslation):
            raise TypeError(
                "SuccessorArchwayAnalysisEngine consumes ArchwayTranslation"
            )
        try:
            from sd_core.analysis.diagram_analysis import (
                open_hybrid_program_session,
            )
            from sd_core.tooling.harness import ProgramResult

            sources = {
                item.module_name: item.source
                for item in translation.modules
            }
            program = (
                ProgramResult.from_module_resolver(
                    sources,
                    _filesystem_module_resolver(
                        translation.dependency_roots
                    ),
                )
                if translation.dependency_roots
                else ProgramResult.from_sources(sources)
            )
            modules = {
                name: item.morphism
                for name, item in program.modules.items()
            }
            session = open_hybrid_program_session(
                modules,
                "main",
                record_events=self.record_events,
            )
            forward = session.run_type_priority_forward()
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
        mapped: list[tuple[Annotation, tuple[Any, ...]]] = []
        for requested in snippet.annotations:
            candidates = _map_observations(observations, requested.location)
            if not candidates:
                candidates = _map_container_path(
                    result.session, requested.location
                )
            if not candidates:
                result.gaps.append(SuccessorGap(
                    requested.location,
                    "provenance_unmapped",
                    snippet.suite_path,
                    requested.types,
                    detail="no diagram type observation at benchmark location",
                ))
                continue
            mapped.append((requested, candidates))

        demanded_addresses = set()
        missing_addresses = _unresolved_query_addresses(
            result.session, mapped
        )
        while new_addresses := tuple(
            address for address in missing_addresses
            if address not in demanded_addresses
        ):
            demanded_addresses.update(new_addresses)
            result.targeted_runs.append(
                result.session.observe(tuple(sorted(
                    new_addresses, key=lambda address: address.id
                )))
            )
            # Targeted refinement may discover a context-specific instance
            # of an observation template (most notably a callable-summary
            # application) while the fallback address that triggered the
            # demand correctly remains open.  Re-read the session catalog so
            # the query consumes the knowledge produced by that demand wave
            # instead of freezing its pre-refinement address set.
            refined_observations = result.session.type_observations()
            mapped = [
                (
                    requested,
                    _map_observations(
                        refined_observations, requested.location
                    )
                    or _map_container_path(
                        result.session, requested.location
                    )
                    or candidates,
                )
                for requested, candidates in mapped
            ]
            missing_addresses = _unresolved_query_addresses(
                result.session, mapped
            )

        for requested, candidates in mapped:
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
                if values != requested.types:
                    classification = (
                        "mapped_imprecise"
                        if requested.types < values
                        else "benchmark_disagreement"
                    )
                    result.gaps.append(SuccessorGap(
                        requested.location,
                        classification,
                        snippet.suite_path,
                        requested.types,
                        tuple(item.address.id for item in candidates),
                        f"resolved successor types: {sorted(values)!r}",
                    ))
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


def _unresolved_query_addresses(session, mapped):
    """Return new fact roots only for queries with no usable candidate."""

    unresolved = set()
    for _requested, candidates in mapped:
        facts = tuple(
            session.store.resolved(item.address) for item in candidates
        )
        if any(fact is not None and fact.value for fact in facts):
            continue
        unresolved.update(
            item.address
            for item, fact in zip(candidates, facts, strict=True)
            if fact is None or not fact.value
        )
    return tuple(sorted(unresolved, key=lambda address: address.id))


def _map_observations(observations, location: Location):
    exact = tuple(
        item for item in observations
        if _observation_name_matches(item, location.name)
        and item.kind == location.kind
        and _observation_scope_matches(item, location)
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
        if _observation_name_matches(item, location.name)
        and item.kind == location.kind
        and _observation_scope_matches(item, location)
        and item.position is not None
        and item.position.row == location.line
    )


def _observation_scope_matches(
    item, location: Location
) -> bool:
    observed = item.function
    requested = location.function
    if observed == requested:
        return True
    if (
        observed
        and requested
        and observed.endswith(f".{requested}")
    ):
        return True
    if not observed or requested is not None:
        return False
    owner = observed.rsplit(".", 1)[0] if "." in observed else ""
    return bool(
        owner
        and item.name.startswith("self.")
        and location.name
        == f"{owner}.{item.name.removeprefix('self.')}"
    )


def _observation_name_matches(item, requested: str) -> bool:
    if item.name == requested:
        return True
    if not isinstance(item.name, str):
        return False
    if item.kind == "return" and item.name.endswith(f".{requested}"):
        return True
    if not item.function or "." not in item.function:
        return False
    owner = item.function.rsplit(".", 1)[0]
    if not item.name.startswith("self."):
        return False
    return requested == f"{owner}.{item.name.removeprefix('self.')}"


def _map_container_path(session, location: Location):
    """Resolve a concrete nested path through existing slot knowledge."""

    name = location.name
    if not name.endswith("]") or "[" not in name:
        return ()
    base = name.split("[", 1)[0]
    slots = tuple(
        item[1:-1]
        if len(item) >= 2 and item[0] == item[-1] and item[0] in "\"'"
        else item
        for item in re.findall(r"\[([^]]+)\]", name)
    )
    if not slots:
        return ()
    return tuple(
        item for item in session.container_path_observations(base, slots)
        if item.kind == location.kind
        and item.function == location.function
        and item.position is not None
        and item.position.row == location.line
    )


def _typeeval_name(value: str) -> str:
    if value == "builtins.callable":
        return "callable"
    if value == "builtins.NoneType":
        return "Nonetype"
    return value.removeprefix("builtins.")


def audit_successor_typeevalpy(
    benchmark,
    *,
    limit: int | None = None,
    record_events: bool = True,
    suite_prefixes: tuple[str, ...] = (),
    progress: Callable[[int, int], None] | None = None,
) -> SuccessorGapAudit:
    """Run a read-only gap census with one forward session per snippet."""

    from archway_benchmarks.engines.archway import ArchwayTranslationEngine

    translator = ArchwayTranslationEngine(
        corpus_root=benchmark.corpus_root,
        dependency_roots=tuple(
            getattr(benchmark, "dependency_roots", ())
        ),
    )
    analyzer = SuccessorArchwayAnalysisEngine(record_events=record_events)
    adapter = SuccessorTypeEvalPyAdapter()
    snippets = benchmark.load()
    if suite_prefixes:
        snippets = [
            snippet for snippet in snippets
            if snippet.suite_path.startswith(suite_prefixes)
        ]
    if limit is not None:
        snippets = snippets[:limit]
    predictions: dict[Location, frozenset[str]] = {}
    classifications: Counter[str] = Counter()
    groups: Counter[str] = Counter()
    representatives: dict[str, str] = {}
    family_groups: Counter[str] = Counter()
    family_representatives: dict[str, str] = {}
    forward_events = knowledge_deltas = resolved_facts = 0
    targeted_roots = targeted_cache_hits = targeted_events = 0
    targeted_knowledge_deltas = targeted_topology_changes = 0
    for completed, snippet in enumerate(snippets, start=1):
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
            for targeted in result.targeted_runs:
                targeted_roots += len(targeted.roots)
                targeted_cache_hits += targeted.cache_hits
                targeted_events += len(targeted.events)
                targeted_knowledge_deltas += len(targeted.knowledge_deltas)
                targeted_topology_changes += (
                    targeted.topology_generation_after
                    - targeted.topology_generation_before
                )
        category = snippet.suite_path.split("/", 1)[0]
        for gap in result.gaps:
            classifications[gap.classification] += 1
            key = f"{gap.classification}|{category}|{gap.location.kind}"
            groups[key] += 1
            representatives.setdefault(key, snippet.suite_path)
            family_key = (
                f"{gap.classification}|{_suite_family(snippet.suite_path)}|"
                f"{gap.location.kind}"
            )
            family_groups[family_key] += 1
            family_representatives.setdefault(
                family_key, snippet.suite_path
            )
        if progress is not None:
            progress(completed, len(snippets))
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
        family_groups=dict(sorted(family_groups.items())),
        family_representatives=dict(sorted(family_representatives.items())),
        forward_events=forward_events,
        knowledge_deltas=knowledge_deltas,
        resolved_facts=resolved_facts,
        targeted_roots=targeted_roots,
        targeted_cache_hits=targeted_cache_hits,
        targeted_events=targeted_events,
        targeted_knowledge_deltas=targeted_knowledge_deltas,
        targeted_topology_changes=targeted_topology_changes,
    )


def _suite_family(suite_path: str) -> str:
    """Collapse an autogen parameter suffix while preserving the category."""

    category, separator, case = suite_path.partition("/")
    if not separator:
        return suite_path
    family = re.sub(r"_[0-9]+_.*$", "", case)
    return f"{category}/{family}"


def _filesystem_module_resolver(
    roots: tuple[str, ...],
) -> Callable[[str], str | None]:
    """Build frontend-only dotted-module resolution for explicit roots."""

    resolved_roots = tuple(Path(root).resolve() for root in roots)

    def resolve(name: str) -> str | None:
        relative = Path(*name.split("."))
        for root in resolved_roots:
            for candidate in (
                root / relative.with_suffix(".py"),
                root / relative / "__init__.py",
            ):
                if candidate.is_file():
                    return candidate.read_text()
        return None

    return resolve
