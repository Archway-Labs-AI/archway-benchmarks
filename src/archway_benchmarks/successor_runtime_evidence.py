"""Stable benchmark evidence projected from the successor public runtime.

Benchmark adapters must not reach through ``HybridForwardSession`` into a
retired invocation registry.  The successor runtime exposes the semantic
objects that matter: admitted callable-cell applications, reusable summary
instances, and their SCC lifecycle.  This module turns those objects into a
small JSON-compatible diagnostic projection shared by PyCG and TypyBench.
"""

from __future__ import annotations

from typing import Mapping


def callable_runtime_evidence(
    session, *, include_lifecycle: bool = True
) -> Mapping[str, object]:
    """Describe callable application coverage without controlling analysis."""

    context_counts = session.invocation_context_counts()
    input_growth = session.invocation_input_growth_counts()
    admission_counts = session.invocation_admission_counts()
    predicate_cache = session.predicate_reduction_cache_counts()
    lifecycle = (
        session.invocation_summary_telemetry() if include_lifecycle else ()
    )
    return {
        "invocation_context_counts": dict(context_counts),
        "invocation_input_growth_counts": dict(input_growth),
        "invocation_admission_counts": dict(admission_counts),
        "predicate_reduction_cache": dict(predicate_cache),
        "invocation_summary_telemetry": tuple(lifecycle),
        # Refusals were owned by the removed native scalar provider. The
        # provider-neutral runtime currently exposes admitted semantic facts,
        # not that retired diagnostic taxonomy.
        "semantic_call_admission_refusals": (),
    }


__all__ = ("callable_runtime_evidence",)
