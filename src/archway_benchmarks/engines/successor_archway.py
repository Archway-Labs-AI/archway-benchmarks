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
    entry_module: str = "main"
    root_policy: str = ""
    callable_bodies: Any | None = None
    projection: dict[Location, Any] = field(default_factory=dict)
    demand_waves: int = 0
    demand_exhausted: bool = False


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


ROOT_POLICY_ENTRY = "entry_module"
ROOT_POLICY_CALLABLE_BODIES = "entry_module+callable_bodies"
ROOT_POLICIES = (ROOT_POLICY_CALLABLE_BODIES, ROOT_POLICY_ENTRY)


class SuccessorArchwayAnalysisEngine:
    """Translate once and run one coordinated type-priority session.

    ``root_policy`` says which roots the session evaluates before the
    adapter's observation demand: the entry module only, or (the default,
    as the PyCG path does) the entry module and every callable body, so a
    function the entry never calls is still analysed, in its uninvoked-body
    context, without anyone asking for its location.
    """

    name = "archway-successor-analysis"

    def __init__(
        self,
        *,
        record_events: bool = True,
        root_policy: str = ROOT_POLICY_CALLABLE_BODIES,
    ) -> None:
        if root_policy not in ROOT_POLICIES:
            raise ValueError(f"unknown root policy: {root_policy!r}")
        self.record_events = record_events
        self.root_policy = root_policy

    def analyze(self, translation: Any) -> SuccessorArchwayResult:
        if not isinstance(translation, ArchwayTranslation):
            raise TypeError(
                "SuccessorArchwayAnalysisEngine consumes ArchwayTranslation"
            )
        try:
            from sd_core.analysis.diagram_analysis.hybrid_forward import (
                open_hybrid_program_session,
            )
            from sd_core.tooling.harness import ProgramResult
            from sd_core.analysis.diagram_analysis.program import PythonModuleEnvironment

            sources = {
                item.module_name: item.source
                for item in translation.modules
            }
            module_paths = {item.module_name: item.path for item in translation.modules}
            program = (
                ProgramResult.from_module_resolver(
                    sources,
                    _filesystem_module_resolver(
                        translation.dependency_roots, module_paths=module_paths,
                    ),
                )
                if translation.dependency_roots
                else ProgramResult.from_sources(sources)
            )
            modules = {
                name: item.morphism
                for name, item in program.modules.items()
            }
            # The sparse lifted product is the authoritative local carrier
            # for a type-priority workload. Native scalar cells remain the
            # targeted projection mechanism for observations not emitted at
            # a forward or summary boundary; they are not a replacement for
            # coordinated local interpretation of each diagram morphism.
            session = open_hybrid_program_session(
                modules,
                "main",
                record_events=self.record_events,
                module_environments={name: PythonModuleEnvironment(path) for name, path in module_paths.items()},
            )
            # Seed only the explicit program entry. Requested type readouts
            # below extend this same session through shared callable-body
            # workload roots; unrequested bodies are not eager entry points.
            forward_workload = session.run_workload(
                session.plan_signature_workload(
                    (), entry_modules=("main",)
                )
            )
            callable_bodies = (
                session.run_analysis_roots(include_callable_bodies=True)
                if self.root_policy == ROOT_POLICY_CALLABLE_BODIES
                else None
            )
            return SuccessorArchwayResult(
                translation.source,
                translation.path,
                session=session,
                forward=forward_workload.seed_run,
                root_policy=self.root_policy,
                callable_bodies=callable_bodies,
            )
        except Exception as exc:
            return SuccessorArchwayResult(
                translation.source,
                translation.path,
                error=f"{type(exc).__name__}: {exc}",
            )


class SuccessorTypeEvalPyAdapter(AnalysisResultAdapter):
    """Project the engine's own type observations onto TypeEvalPy locations.

    A prediction comes only from what the engine reports. The adapter first
    demands every open observation the session catalogues (independent of
    the benchmark), then projects each observation that denotes a
    TypeEvalPy-annotatable entity onto a ``Location`` with the convention in
    :func:`project_typeevalpy_locations`. The snippet's annotations are read
    only afterwards, to classify gaps for reporting; they never choose a
    location, a spelling or a demand.
    """

    def to_annotations(
        self, result: Any, snippet: Snippet
    ) -> list[Annotation]:
        if not isinstance(result, SuccessorArchwayResult):
            raise TypeError(
                "SuccessorTypeEvalPyAdapter requires SuccessorArchwayResult"
            )
        if result.error or result.session is None:
            return []
        demand_open_observations(result)
        result.projection = project_typeevalpy_locations(
            result.session, snippet.file_path, result.entry_module
        )
        predictions = [
            Annotation(location, item.types)
            for location, item in result.projection.items()
            if item.types
        ]
        # Reporting only: predictions are fixed above.
        result.gaps.extend(classify_gaps(snippet, result.projection))
        return predictions


@dataclass(frozen=True)
class ProjectedLocation:
    """The engine's answer at one TypeEvalPy location.

    ``types`` joins the resolved type sets of every observation that projects
    here (``address_ids``); ``open_address_ids`` are contributing
    observations whose value is not used: resolved to nothing, or an
    uninvoked-body context superseded by a reached one. A location with no
    used value is kept for diagnostics but is not a prediction.
    """

    location: Location
    types: frozenset[str]
    address_ids: tuple[str, ...]
    open_address_ids: tuple[str, ...]


_MAX_DEMAND_WAVES = 16


def demand_open_observations(result: SuccessorArchwayResult) -> None:
    """Demand every unresolved catalogued observation until none is new.

    The address set comes from ``session.type_observations()`` alone. Each
    wave can refine callable contexts and so catalogue new observations; the
    loop re-reads the catalogue and stops when a wave adds no new open
    address, or after ``_MAX_DEMAND_WAVES`` waves (recorded on the result).
    """

    session = result.session
    demanded: set[Any] = set()
    for _wave in range(_MAX_DEMAND_WAVES):
        open_addresses = tuple(sorted(
            {
                item.address
                for item in session.type_observations()
                if item.address not in demanded
                and not _resolved_types(session, item.address)
            },
            key=lambda address: address.id,
        ))
        if not open_addresses:
            return
        demanded.update(open_addresses)
        workload = session.run_workload(
            session.plan_signature_workload(open_addresses)
        )
        result.targeted_runs.extend(workload.targeted_runs)
        result.demand_waves += 1
    result.demand_exhausted = True


def project_typeevalpy_locations(
    session: Any, file_path: str, entry_module: str
) -> dict[Location, ProjectedLocation]:
    """Project engine observations onto TypeEvalPy locations.

    Convention (engine observation -> TypeEvalPy record), reading only the
    observation fields ``kind``, ``name``, ``function``, ``position``,
    ``definition_position``, ``boundary_role``, ``address`` and ``module``:

    * Only observations of the snippet's own module (``entry_module``) with a
      source position are projected; ``line`` is ``position.row`` and
      ``col_offset`` is ``position.col + 1`` (TypeEvalPy columns are
      1-indexed, the engine's are AST 0-indexed).
    * **Variable** (``variable`` record, ``function`` = enclosing scope or
      absent at module level): a binding result (``BindingSubject``: an
      assignment, augmented-assignment, walrus, loop or comprehension
      target), an instance attribute (``InstanceAttributeSubject``, spelled
      by the engine as ``<receiver>.<attr>``, e.g. ``self.x``, scoped to the
      method), a class attribute (``ClassAttributeSubject``, spelled
      ``<Class>.<attr>``, no function), and a concrete container slot of
      any of those (``ContainerSlotSubject``, spelled ``name[key]`` with the
      engine's ``slot_display``; nested slots are followed through the
      engine's slot-referent facts, see :func:`_nested_slot_observations`).
      Not projected: the binding a ``def``, ``class`` or ``import``
      statement creates (TypeEvalPy annotates assignments and the
      callable's return, not definition or import names), summary slots
      ``[*]`` (no concrete key), anonymous receivers (``<receiver>``), and
      every ``WireSubject`` observation (use-site reads and internal
      subexpressions: loads, calls, literals, ``()``).
      Statement bindings are recognised from the engine's observations:
      a ``def`` binding's scope-qualified name is a callable the engine
      reports (by return or parameter observations) and its row is that
      callable's definition row; a ``class`` binding's qualified name owns
      class attributes and its row is not after the first of them, or the
      same row carries the class statement's ``builtins.type`` output wire
      of the same name left of the target; an ``import`` binding's row
      carries a ``builtins.module`` output wire left of the target (or, for
      ``import m`` / ``import m.sub``, at the target, named ``m`` or
      ``m.<...>``).
    * **Parameter** (``parameter`` + ``function`` = the engine's qualified
      callable name, ``lambda`` for lambdas): every ``parameter``
      observation except a method receiver. A method is a callable whose
      qualified name is also a class attribute; its receiver is its first
      parameter by position, unless the engine types the class attribute
      ``builtins.staticmethod``.
    * **Return** (``function`` = the engine's qualified callable name): a
      ``return`` observation. ``line`` is the definition row; the column is
      the callable's name column, read from the ``def`` binding observation
      on that row (fallback: ``definition_position.col`` + 4, the width of
      ``def``). Not projected: lambda returns (TypeEvalPy keys returns by
      function name and a lambda has none) and ``__init__`` returns
      (TypeEvalPy does not annotate constructors' returns).

    Several observations can project to one location (one entity analysed
    in several contexts, or seen as both a class-context and a module
    attribute); their resolved type sets are joined, which is the engine's
    context-insensitive answer at that location. A context the engine minted
    for a body the entry never invoked contributes only when no reached
    context has a value there: the uninvoked analysis is the engine's
    answer for code it did not reach, not a widening of code it did.
    """

    from sd_core.analysis.diagram_analysis.knowledge import (
        BindingSubject,
        BoundaryRole,
        ClassAttributeSubject,
        ContainerSlotSubject,
        InstanceAttributeSubject,
        WireSubject,
    )

    observations = tuple(
        item for item in session.type_observations()
        if item.module is not None
        and item.module.dotted == entry_module
        and item.position is not None
    )

    callable_rows: dict[str, set[int]] = {}
    for item in observations:
        if item.definition_position is None:
            continue
        if item.kind == "return":
            callable_rows.setdefault(item.name, set()).add(
                item.definition_position.row
            )
        elif item.kind == "parameter" and item.function:
            callable_rows.setdefault(item.function, set()).add(
                item.definition_position.row
            )

    class_attribute_types: dict[str, set[str]] = {}
    class_attribute_rows: dict[str, int] = {}
    for item in observations:
        if isinstance(item.address.subject, ClassAttributeSubject):
            class_attribute_types.setdefault(item.name, set()).update(
                _resolved_types(session, item.address)
            )
            owner = item.name.rsplit(".", 1)[0]
            class_attribute_rows[owner] = min(
                class_attribute_rows.get(owner, item.position.row),
                item.position.row,
            )

    def qualified_binding(item) -> str:
        if isinstance(item.address.subject, ClassAttributeSubject):
            return item.name
        return f"{item.function}.{item.name}" if item.function else item.name

    statement_outputs: dict[int, list[tuple[int, str, frozenset[str]]]] = {}
    for item in observations:
        if (
            isinstance(item.address.subject, WireSubject)
            and item.boundary_role is BoundaryRole.OUTPUT
            and item.kind == "variable"
        ):
            statement_outputs.setdefault(item.position.row, []).append((
                item.position.col,
                item.name,
                _resolved_types(session, item.address),
            ))

    def is_statement_binding(item) -> bool:
        """A binding made by a def, class or import statement."""

        qualified = qualified_binding(item)
        row, col = item.position.row, item.position.col
        if row in callable_rows.get(qualified, ()):
            return True
        for owner, first_row in class_attribute_rows.items():
            if (
                (qualified == owner or qualified.endswith(f".{owner}"))
                and row <= first_row
            ):
                return True
        if not isinstance(item.address.subject, BindingSubject):
            return False
        for wire_col, wire_name, wire_types in statement_outputs.get(row, ()):
            if (
                wire_types == {"builtins.type"}
                and wire_name == item.name
                and wire_col < col
            ):
                return True
            if wire_types == {"builtins.module"} and (
                wire_col < col
                or (
                    wire_col == col
                    and (
                        wire_name == item.name
                        or wire_name.startswith(f"{item.name}.")
                    )
                )
            ):
                return True
        return False

    definition_columns: dict[tuple[str, int], int] = {}
    for item in observations:
        if (
            item.kind in {"variable", "class_field"}
            and isinstance(
                item.address.subject, (BindingSubject, ClassAttributeSubject)
            )
            and item.position.row
            in callable_rows.get(qualified_binding(item), ())
        ):
            definition_columns[
                (qualified_binding(item), item.position.row)
            ] = item.position.col

    receivers: set[tuple[str, int, int]] = set()
    first_parameter: dict[str, tuple[int, int]] = {}
    for item in observations:
        if item.kind == "parameter" and item.function:
            key = (item.position.row, item.position.col)
            first_parameter[item.function] = min(
                first_parameter.get(item.function, key), key
            )
    for function, (row, col) in first_parameter.items():
        # Class attributes are spelled from the class downwards; a class
        # defined inside a function has a longer callable name.
        owners = [
            types for name, types in class_attribute_types.items()
            if function == name or function.endswith(f".{name}")
        ]
        if owners and not any(
            "builtins.staticmethod" in types for types in owners
        ):
            receivers.add((function, row, col))

    projected: list[tuple[Location, Any]] = []
    for item in observations:
        subject = item.address.subject
        row, col = item.position.row, item.position.col
        if item.kind == "return":
            if (
                item.name == "lambda"
                or item.name.rsplit(".", 1)[-1] == "__init__"
                or item.definition_position is None
            ):
                continue
            row = item.definition_position.row
            col = definition_columns.get(
                (item.name, row), item.definition_position.col + 4
            )
            location = Location(
                file_path, row, col + 1, "return", item.name, None
            )
        elif item.kind == "parameter":
            if not item.function or (item.function, row, col) in receivers:
                continue
            location = Location(
                file_path, row, col + 1, "parameter", item.name,
                item.function,
            )
        elif item.kind in {"variable", "class_field"}:
            if isinstance(subject, WireSubject) or not isinstance(
                subject,
                (
                    BindingSubject,
                    ClassAttributeSubject,
                    ContainerSlotSubject,
                    InstanceAttributeSubject,
                ),
            ):
                continue
            if (
                not item.name
                or "<" in item.name
                or "[*]" in item.name
                or is_statement_binding(item)
            ):
                continue
            location = Location(
                file_path, row, col + 1, "variable", item.name,
                item.function,
            )
        else:
            continue
        projected.append((location, item.address))

    for name, position, function, address in _nested_slot_observations(
        session, entry_module
    ):
        projected.append((
            Location(
                file_path, position.row, position.col + 1, "variable",
                name, function,
            ),
            address,
        ))

    grouped: dict[Location, list[Any]] = {}
    for location, address in projected:
        addresses = grouped.setdefault(location, [])
        if address not in addresses:
            addresses.append(address)
    out: dict[Location, ProjectedLocation] = {}
    for location in sorted(grouped, key=_location_order):
        addresses = sorted(grouped[location], key=lambda item: item.id)
        resolved = {
            address: _resolved_types(session, address)
            for address in addresses
        }
        if any(
            values and not _uninvoked_context(address.context)
            for address, values in resolved.items()
        ):
            resolved = {
                address: (
                    frozenset() if _uninvoked_context(address.context)
                    else values
                )
                for address, values in resolved.items()
            }
        out[location] = ProjectedLocation(
            location,
            frozenset(
                _typeeval_name(value)
                for values in resolved.values() for value in values
            ),
            tuple(address.id for address in addresses if resolved[address]),
            tuple(
                address.id for address in addresses if not resolved[address]
            ),
        )
    return out


_MAX_SLOT_DEPTH = 4


def _nested_slot_observations(session, entry_module: str):
    """Follow concrete container slots below the first level.

    The engine catalogues first-level slots of a named container
    (``d['a']``). Deeper concrete slots (``d['a']['b']``) are present as
    slot facts reached through slot-referent facts; this walk reads those
    resolved facts for every named-container template of the entry module
    and yields one ``(name, position, function, address)`` per concrete
    slot at depth two or more. Summary/element slots are not followed.
    """

    from sd_core.analysis.diagram_analysis.container_knowledge import (
        CONTAINER_REFERENTS,
        CONTAINER_SLOT_REFERENTS,
        CONTAINER_SLOT_TYPE_OF,
    )
    from sd_core.analysis.diagram_analysis.hybrid_observations import (
        slot_display,
    )
    from sd_core.analysis.diagram_analysis.knowledge import (
        ContainerSlotSubject,
        FactAddress,
    )

    plan = session.module_plans.get(entry_module) if session.module_plans else session.plan
    if plan is None:
        return
    resolved_facts = session.store.snapshot().resolved_facts
    slots_by_allocation: dict[tuple[str, str], list[Any]] = {}
    for address in resolved_facts:
        if address.family == CONTAINER_SLOT_TYPE_OF and isinstance(
            address.subject, ContainerSlotSubject
        ):
            slots_by_allocation.setdefault(
                (
                    address.subject.observation_morphism_id,
                    address.subject.allocation_morphism_id,
                ),
                [],
            ).append(address)

    def walk(template, allocations, prefix, depth, seen):
        for allocation in sorted(allocations):
            if allocation in seen:
                continue
            for address in sorted(
                slots_by_allocation.get(
                    (template.subject.morphism_id, allocation), ()
                ),
                key=lambda item: item.id,
            ):
                slot = address.subject.slot
                if ":" not in slot or slot.startswith("summary:"):
                    continue
                name = f"{prefix}{slot_display(slot)}"
                yield name, template.position, template.function, address
                if depth >= _MAX_SLOT_DEPTH:
                    continue
                referent = resolved_facts.get(FactAddress(
                    family=CONTAINER_SLOT_REFERENTS,
                    subject=address.subject,
                    context=address.context,
                    assumptions=address.assumptions,
                    projection=address.projection,
                ))
                if referent is not None and referent.value:
                    yield from walk(
                        template, referent.value, name, depth + 1,
                        seen | {allocation},
                    )

    for template in plan.container_templates:
        if template.position is None:
            continue
        for address, fact in resolved_facts.items():
            if (
                address.family == CONTAINER_REFERENTS
                and address.subject == template.subject
                and fact.value
            ):
                yield from walk(
                    template, fact.value, template.name, 1, frozenset()
                )


def classify_gaps(
    snippet: Snippet, projection: dict[Location, ProjectedLocation]
) -> list[SuccessorGap]:
    """Compare finished predictions with the answer key, for reporting."""

    gaps: list[SuccessorGap] = []
    expected = {item.location: item.types for item in snippet.annotations}
    for location, types in expected.items():
        item = projection.get(location)
        if item is None:
            gaps.append(SuccessorGap(
                location, "provenance_unmapped", snippet.suite_path, types,
                detail="no engine observation projects to this location",
            ))
        elif not item.types:
            gaps.append(SuccessorGap(
                location, "mapped_open", snippet.suite_path, types,
                item.open_address_ids,
                "engine observations at this location resolved to nothing",
            ))
        elif item.types != types:
            gaps.append(SuccessorGap(
                location,
                "mapped_imprecise" if types < item.types
                else "benchmark_disagreement",
                snippet.suite_path,
                types,
                item.address_ids,
                f"resolved successor types: {sorted(item.types)!r}",
            ))
    for location, item in projection.items():
        if item.types and location not in expected:
            gaps.append(SuccessorGap(
                location, "unexpected_prediction", snippet.suite_path,
                frozenset(), item.address_ids,
                f"resolved successor types: {sorted(item.types)!r}",
            ))
    return gaps


def _resolved_types(session, address) -> frozenset[str]:
    fact = session.store.resolved(address)
    return frozenset(fact.value) if fact is not None and fact.value else frozenset()


def _uninvoked_context(context: str) -> bool:
    """Whether the engine minted this context for a body never invoked.

    The engine names those contexts ``context:module:<m>:uninvoked:<body>``
    (callable bodies the entry did not reach) and
    ``context:uninvoked-body:<body>`` (catalogue fallback).
    """

    return ":uninvoked:" in context or context.startswith(
        "context:uninvoked-body:"
    )


def _location_order(location: Location):
    return (
        location.line, location.col or 0, location.kind, location.name,
        location.function or "",
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
    root_policy: str = ROOT_POLICY_CALLABLE_BODIES,
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
    analyzer = SuccessorArchwayAnalysisEngine(
        record_events=record_events, root_policy=root_policy
    )
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
    *, module_paths: dict[str, str] | None = None,
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
                    if module_paths is not None:
                        module_paths[name] = str(candidate)
                    return candidate.read_text()
        return None

    return resolve
