"""Stable benchmark evidence projected from the successor public runtime.

Benchmark adapters must not reach through ``HybridForwardSession`` into a
retired invocation registry.  The successor runtime exposes the semantic
objects that matter: admitted callable-cell applications, reusable summary
instances, and their SCC lifecycle.  This module turns those objects into a
small JSON-compatible diagnostic projection shared by PyCG and TypyBench.
"""

from __future__ import annotations

from collections import Counter
from typing import Mapping


def callable_runtime_evidence(
    session, *, include_lifecycle: bool = True
) -> Mapping[str, object]:
    """Describe callable application coverage without controlling analysis."""

    entry_admissions = session.native_callable_cell_admissions()
    completion_admissions = (
        session.native_callable_cell_completion_admissions()
    )
    summary_admissions = session.native_callable_cell_summary_admissions()
    summary_instances = session.native_callable_cell_summary_instances()
    lifecycle = (
        session.native_callable_summary_component_lifecycle()
        if include_lifecycle else ()
    )

    precise_admissions = (*entry_admissions, *completion_admissions)
    applications = {
        (
            admission.application.callsite_morphism_id,
            admission.application.caller_context,
            admission.application.body_morphism_id,
            admission.application.callee_context,
            admission.partition.id,
        )
        for admission in precise_admissions
    }
    partitions = {
        admission.partition.id: admission.partition
        for admission in (*precise_admissions, *summary_admissions)
    }
    bodies = {
        admission.application.body_morphism_id
        for admission in summary_admissions
    }
    partition_kinds = Counter(
        type(partition).__name__ for partition in partitions.values()
    )

    provider = session.native_scalar_provider
    refusals = (
        provider.semantic_call_admission_refusals()
        if provider is not None else ()
    )
    return {
        "invocation_context_counts": {
            "precise": len(applications),
            "summary": len(summary_admissions),
            "summary_registered": len(summary_instances),
            "bodies_summarized": len(bodies),
        },
        "invocation_input_growth_counts": {
            "admitted_applications": len(applications),
            "input_partitions": len(partitions),
            "summary_instances": len(summary_instances),
        },
        "invocation_admission_counts": dict(sorted(partition_kinds.items())),
        "invocation_summary_telemetry": tuple(lifecycle),
        "semantic_call_admission_refusals": tuple(refusals),
    }


__all__ = ("callable_runtime_evidence",)
