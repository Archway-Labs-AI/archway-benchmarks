"""In-process TypeEvalPy bridge for Archway's coordinated analysis session.

This bridge is intentionally thin: the benchmark supplies requested source
locations, while type values and dependency traces come only from coordinated
runtime facts. It does not invoke the legacy monolithic analysis product.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from archway_benchmarks.benchmarks.base import AnalysisResultAdapter
from archway_benchmarks.engines.archway import ArchwayTranslation
from archway_benchmarks.types import Annotation, Snippet


@dataclass
class CoordinatedArchwayResult:
    source: str
    path: str
    build: Any | None = None
    session: Any | None = None
    global_context: Any | None = None
    error: str | None = None
    diagnostics: list[str] | None = None


class CoordinatedArchwayAnalysisEngine:
    """Build one analysis-neutral session; consumers issue targeted demands."""

    name = "archway-coordinated-analysis"

    def analyze(self, translation: Any) -> CoordinatedArchwayResult:
        if not isinstance(translation, ArchwayTranslation):
            raise TypeError(
                "CoordinatedArchwayAnalysisEngine consumes ArchwayTranslation"
            )
        try:
            from sd_core.analysis.runtime.call_targets import InvocationContext
            from sd_core.analysis.runtime.coordinated_session import (
                CoordinatedAnalysisSession,
            )
            from sd_core.runners.contextual_call_resolution import (
                build_python_callable_index,
            )

            build = build_python_callable_index(
                translation.source, module_name="main"
            )
            session = CoordinatedAnalysisSession(build.index)
            context = session.admit_context(InvocationContext())
            return CoordinatedArchwayResult(
                translation.source, translation.path, build, session, context,
                diagnostics=[],
            )
        except Exception as exc:
            return CoordinatedArchwayResult(
                translation.source,
                translation.path,
                error=f"{type(exc).__name__}: {exc}",
            )


class CoordinatedTypeEvalPyAdapter(AnalysisResultAdapter):
    """Resolve only TypeEvalPy-requested locations through typed demands."""

    def to_annotations(
        self, result: Any, snippet: Snippet
    ) -> list[Annotation]:
        if not isinstance(result, CoordinatedArchwayResult):
            raise TypeError(
                "CoordinatedTypeEvalPyAdapter requires CoordinatedArchwayResult"
            )
        if result.error:
            return []

        out: list[Annotation] = []
        _seed_module_outputs(result)
        _seed_constructor_contexts(result)
        for requested in snippet.annotations:
            try:
                types = _demand_location(result, requested)
            except Exception as exc:
                assert result.diagnostics is not None
                result.diagnostics.append(
                    f"{requested.location}: {type(exc).__name__}: {exc}"
                )
                continue
            if types:
                out.append(Annotation(requested.location, types))
        return out


def _demand_location(
    result: CoordinatedArchwayResult, requested: Annotation
) -> frozenset[str]:
    from sd_core.analysis.runtime.coordinated_session import CoordinatedDemand
    from sd_core.analysis.runtime.type_facts import type_judgment_address

    index = result.build.index
    session = result.session
    location = requested.location

    def demand(value_location, context) -> frozenset[str]:
        response = session.demand(CoordinatedDemand(
            type_judgment_address(value_location, context, index.revision),
            "benchmark:typeevalpy",
        ))
        return response.requested.payload.types

    def in_requested_function(declaration: str) -> bool:
        if location.function is None:
            return declaration.endswith(":<module>")
        if location.function == "lambda":
            return "<lambda" in declaration
        return declaration.endswith(f":{location.function}")

    if location.kind == "variable":
        if "." in location.name and location.function is not None:
            attribute_name = location.name.rsplit(".", 1)[-1]
            writes = [
                item for item in index.instance_writes
                if item.attribute_name == attribute_name
                and in_requested_function(item.boundary.declaration)
            ]
            positioned = [
                item for item in writes
                if index.value_node(item.value).control_position[0]
                == location.line
            ]
            writes = positioned or writes
            types: set[str] = set()
            for context in tuple(session.value_inputs.contexts):
                for write in writes:
                    types.update(demand(write.value, context))
            return frozenset(types)
        indexed_base = location.name.split("[", 1)[0]
        is_indexed = indexed_base != location.name
        candidates = [
            node for node in index.value_nodes
            if node.location.role == f"module_binding_value:{indexed_base}"
            and in_requested_function(
                getattr(node.location.owner, "declaration", "")
            )
        ]
        # Function-local assignments currently retain their source role rather
        # than the module-binding label; use the stable binding suffix there.
        if not candidates:
            candidates = [
                node for node in index.value_nodes
                if (
                    node.location.role.endswith(f"binding_value:{indexed_base}")
                    or node.location.role.startswith(f"binding:{indexed_base}:")
                )
                and (
                    in_requested_function(
                        getattr(node.location.owner, "declaration", "")
                    )
                )
            ]
        candidates = [
            node for node in candidates if node.control_position[0] == location.line
        ] or candidates
        types: set[str] = set()
        contexts = (
            tuple(session.value_inputs.contexts)
            if location.function is not None
            else (result.global_context,)
        )
        for context in contexts:
            for node in candidates:
                if not is_indexed:
                    types.update(demand(node.location, context))
                    continue
                from sd_core.analysis.runtime.coordinated_session import (
                    CoordinatedDemand,
                )
                from sd_core.analysis.runtime.type_facts import (
                    container_element_type_address,
                )
                from sd_core.analysis.runtime.value_flow_facts import (
                    value_flow_address,
                )
                flowed = session.demand(CoordinatedDemand(
                    value_flow_address(
                        node.location, context, index.revision
                    ),
                    "benchmark:typeevalpy:container-base",
                )).requested.payload
                for region in flowed.container_regions:
                    element = session.demand(CoordinatedDemand(
                        container_element_type_address(
                            region, index.revision
                        ),
                        "benchmark:typeevalpy:container-element",
                    )).requested.payload
                    types.update(element.types)
        return frozenset(types)

    if location.kind == "return":
        boundaries = [
            item.boundary for item in index.returns
            if item.boundary.declaration.endswith(f":{location.name}")
        ]
        types: set[str] = set()
        contexts = tuple(session.value_inputs.contexts) or (result.global_context,)
        for boundary in boundaries:
            if any(item.boundary == boundary for item in index.yields):
                types.add("generator")
            observation = index.return_observation(boundary)
            for context in contexts:
                for value in observation.values:
                    types.update(demand(value, context))
        return frozenset(types)

    if location.kind == "parameter":
        # First demand module outputs. This discovers only contexts reachable
        # from actual calls; parameters are never solved by a greedy pre-pass.
        for node in index.value_nodes:
            if node.location.role.startswith("module_binding_value:"):
                demand(node.location, result.global_context)
        candidates = [
            node for node in index.value_nodes
            if node.parameter_name == location.name
            and in_requested_function(
                getattr(node.location.owner, "declaration", "")
            )
        ]
        types: set[str] = set()
        for context in tuple(session.value_inputs.contexts):
            for node in candidates:
                types.update(demand(node.location, context))
        return frozenset(types)

    return frozenset()


def _seed_module_outputs(result: CoordinatedArchwayResult) -> None:
    """Demand externally visible module values, discovering reachable contexts."""
    from sd_core.analysis.runtime.coordinated_session import CoordinatedDemand
    from sd_core.analysis.runtime.type_facts import type_judgment_address

    index = result.build.index
    for node in index.value_nodes:
        if not (
            node.location.role.startswith("module_binding_value:")
            or (
                node.location.role.startswith("binding:")
                and getattr(node.location.owner, "declaration", "").endswith(
                    ":<module>"
                )
            )
        ):
            continue
        try:
            result.session.demand(CoordinatedDemand(
                type_judgment_address(
                    node.location, result.global_context, index.revision
                ),
                "benchmark:typeevalpy:module-output",
            ))
        except Exception as exc:
            assert result.diagnostics is not None
            result.diagnostics.append(
                f"{node.location.role}: {type(exc).__name__}: {exc}"
            )


def _seed_constructor_contexts(result: CoordinatedArchwayResult) -> None:
    """Demand reachable constructors and admit their initializer contexts."""
    from sd_core.analysis.runtime.call_targets import InvocationContext
    from sd_core.analysis.runtime.constructor_facts import (
        constructor_invocation_address,
    )
    from sd_core.analysis.runtime.coordinated_session import CoordinatedDemand

    index = result.build.index
    for node in index.value_nodes:
        if node.allocation_class is None or node.callsite is None:
            continue
        try:
            constructor = result.session.demand(CoordinatedDemand(
                constructor_invocation_address(
                    node.callsite, result.global_context, index.revision
                ),
                "benchmark:typeevalpy:constructor-context",
            )).requested.payload
            arguments = constructor.arguments
            result.session.admit_context(InvocationContext.create(
                callable_arguments=dict(arguments.callable_arguments),
                class_arguments=dict(arguments.class_arguments),
                region_arguments=dict(arguments.region_arguments),
                container_arguments=dict(arguments.container_arguments),
                concrete_arguments=dict(arguments.concrete_arguments),
                type_arguments=dict(arguments.type_arguments),
            ))
        except Exception as exc:
            assert result.diagnostics is not None
            result.diagnostics.append(
                f"{node.location.role}: {type(exc).__name__}: {exc}"
            )
