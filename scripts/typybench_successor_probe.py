"""Diagnostic entry point for one successor TypyBench repository workload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from archway_benchmarks.typybench_archway_emit import _run_successor_repo_probe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("engine_worktree", type=Path)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--demand-limit", type=int)
    parser.add_argument("--checkpoint-roots", action="store_true")
    parser.add_argument("--checkpoint-size", type=int, default=8)
    parser.add_argument("--checkpoint-tail-start", type=int)
    parser.add_argument("--checkpoint-tail-count", type=int)
    parser.add_argument(
        "--checkpoint-batch-start",
        type=int,
        help="replay and preserve the exact production cohort partition",
    )
    parser.add_argument("--checkpoint-batch-count", type=int)
    parser.add_argument("--body-label", action="append", dest="body_labels")
    parser.add_argument("--body-timeout", type=int)
    parser.add_argument("--callable-input-exact-limit", type=int)
    parser.add_argument("--sample-rate-hz", type=float)
    parser.add_argument("--sample-body-label")
    parser.add_argument(
        "--sample-forward",
        action="store_true",
        help="sample only the initial forward-seeding phase",
    )
    parser.add_argument(
        "--forward-timeout",
        type=int,
        help="gracefully cut off forward seeding and retain its sample",
    )
    parser.add_argument("--record-timings", action="store_true")
    parser.add_argument(
        "--progress-log",
        type=Path,
        help="persist worker progress as it is emitted, including on timeout",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        help="persist the final diagnostic report instead of printing it",
    )
    parser.add_argument(
        "--disable-cyclic-gc",
        action="store_true",
        dest="disable_cyclic_gc",
        help="diagnose an isolated arena without cyclic-GC graph scans",
    )
    parser.add_argument(
        "--cyclic-gc",
        action="store_false",
        dest="disable_cyclic_gc",
        help="retain cyclic GC for an arena A/B control",
    )
    parser.set_defaults(disable_cyclic_gc=True)
    parser.add_argument(
        "--compact-diagnostics",
        action="store_true",
        help="emit bounded top-N diagnostic maps and only the terminal cohorts",
    )
    parser.add_argument(
        "--production-light",
        action="store_true",
        help="disable detailed per-cohort diagnostic attribution",
    )
    parser.add_argument(
        "--include-variables",
        action="store_true",
        help="include lexical-variable observations in the requested workload",
    )
    parser.add_argument(
        "--collect-predictions",
        action="store_true",
        help="exercise the prediction projection used by the corpus emitter",
    )
    parser.add_argument(
        "--contextual-summary-evaluation",
        action="store_true",
        help=(
            "expand callable applications into the diagnostic contextual "
            "production graph instead of using composed summaries"
        ),
    )
    args = parser.parse_args()
    if (
        args.body_timeout is not None
        and not args.body_labels
        and args.sample_body_label is None
    ):
        parser.error(
            "--body-timeout requires --body-label or --sample-body-label"
        )
    if args.sample_body_label is not None and args.sample_rate_hz is None:
        parser.error("--sample-body-label requires --sample-rate-hz")
    result = _run_successor_repo_probe(
        engine_worktree=args.engine_worktree,
        source_root=args.source_root,
        runner=("hatch", "run", "python"),
        timeout=args.timeout,
        progress_log=args.progress_log,
        demand_limit=args.demand_limit,
        checkpoint_roots=args.checkpoint_roots,
        checkpoint_size=args.checkpoint_size,
        checkpoint_tail_start=args.checkpoint_tail_start,
        checkpoint_tail_count=args.checkpoint_tail_count,
        checkpoint_batch_start=args.checkpoint_batch_start,
        checkpoint_batch_count=args.checkpoint_batch_count,
        body_labels=tuple(args.body_labels or ()),
        body_timeout=args.body_timeout,
        callable_input_exact_limit=args.callable_input_exact_limit,
        sample_rate_hz=args.sample_rate_hz,
        sample_body_label=args.sample_body_label,
        sample_forward=args.sample_forward,
        forward_timeout=args.forward_timeout,
        record_timings=args.record_timings,
        diagnostic_details=not args.production_light,
        collect_predictions=args.collect_predictions,
        contextual_summary_evaluation=args.contextual_summary_evaluation,
        disable_cyclic_gc=args.disable_cyclic_gc,
        observation_kinds=frozenset((
            "parameter",
            "return",
            *(("variable",) if args.include_variables else ()),
        )),
    )
    summary = result.get("analysis_summary") or {}
    scheduler = summary.get("scheduler") or {}
    worklist = scheduler.get("worklist_schedule_counts") or {}
    top_families = sorted(
        (scheduler.get("production_executions_by_family") or {}).items(),
        key=lambda item: (-item[1], item[0]),
    )[:12]
    top_family_seconds = sorted(
        (scheduler.get("production_seconds_by_family") or {}).items(),
        key=lambda item: (-item[1], item[0]),
    )[:12]
    top_restart_operations = sorted(
        (
            (key.removeprefix("topology_restart_operation:"), value)
            for key, value in worklist.items()
            if key.startswith("topology_restart_operation:")
        ),
        key=lambda item: (-item[1], item[0]),
    )[:12]
    top_restart_reasons = sorted(
        (
            (key.removeprefix("topology_restart_reason:"), value)
            for key, value in worklist.items()
            if key.startswith("topology_restart_reason:")
        ),
        key=lambda item: (-item[1], item[0]),
    )[:12]
    top_restart_operation_reasons = sorted(
        (
            (key.removeprefix(
                "topology_restart_operation_reason:"
            ).split("\0", 1), value)
            for key, value in worklist.items()
            if key.startswith("topology_restart_operation_reason:")
        ),
        key=lambda item: (-item[1], item[0]),
    )[:20]
    def top_counts(value: object, limit: int = 20) -> object:
        if not args.compact_diagnostics or not isinstance(value, dict):
            return value
        return sorted(
            value.items(), key=lambda item: (-item[1], item[0])
        )[:limit]

    body_profiles = summary.get("body_profiles") or []
    if args.compact_diagnostics:
        body_profiles = [{
            key: value for key, value in profile.items()
            if key not in {"root_id", "root_ids"}
        } for profile in body_profiles[-1:]]
    sampling_profile = summary.get("sampling_profile")
    if args.compact_diagnostics and isinstance(sampling_profile, dict):
        sampling_profile = {
            key: value for key, value in sampling_profile.items()
            if key not in {"stacks", "top_stacks"}
        }
    replay_hotspots = summary.get("production_replay_hotspots") or []
    replay_operation_hotspots = summary.get(
        "production_replay_operation_hotspots"
    ) or []
    if args.compact_diagnostics:
        replay_hotspots = [
            {
                key: item.get(key)
                for key in (
                    "family", "operation", "executions", "replays",
                    "semantic_changes",
                )
            }
            for item in replay_hotspots[:12]
        ]
    report = {
        "ok": result.get("ok"),
        "error": result.get("error"),
        "phase_seconds": summary.get("phase_seconds"),
        "phase_progress": summary.get("phase_progress"),
        "active_translation_file": summary.get("active_translation_file"),
        "active_body": summary.get("active_body"),
        "slow_translation_files": summary.get("slow_translation_files"),
        "modules": summary.get("modules"),
        "observations": summary.get("observations"),
        "signature_demands": summary.get("targeted_addresses"),
        "requested_addresses": summary.get("requested_addresses"),
        "requested_body_roots": summary.get("requested_body_roots"),
        "signature_body_roots": summary.get("signature_body_roots"),
        "component_hotspots": summary.get("component_hotspots"),
        "morphism_transfer_reuse": (
            summary.get("morphism_transfer_reuse")
        ),
        "morphism_transfer_reuse_by_operation": (
            top_counts(
                summary.get("morphism_transfer_reuse_by_operation"), 40
            )
        ),
        "atomic_effect_gaps": summary.get("atomic_effect_gaps"),
        "morphism_fact_output_barriers": summary.get(
            "morphism_fact_output_barriers"
        ),
        "morphism_read_intersections": (
            top_counts(summary.get("morphism_read_intersections"), 30)
        ),
        "invocation_contexts": top_counts(summary.get("invocation_contexts")),
        "invocation_inputs": top_counts(summary.get("invocation_inputs")),
        "invocation_admissions": top_counts(summary.get("invocation_admissions")),
        "invocation_application_hotspots": summary.get(
            "invocation_application_hotspots"
        ),
        "invocation_application_runtime_hotspots": summary.get(
            "invocation_application_runtime_hotspots"
        ),
        "sampling_profile": sampling_profile,
        "unresolved_summary_bodies": summary.get(
            "unresolved_summary_bodies"
        ),
        "body_profiles": body_profiles,
        "body_plan": (
            None if args.compact_diagnostics else summary.get("body_plan")
        ),
        "timed_out_body": summary.get("timed_out_body"),
        "timed_out_forward": summary.get("timed_out_forward"),
        "unique_productions": scheduler.get("unique_production_count"),
        "production_executions": scheduler.get("production_execution_count"),
        "repeated_productions": scheduler.get("repeated_production_count"),
        "production_replay_hotspots": replay_hotspots,
        "production_replay_operation_hotspots": replay_operation_hotspots,
        "affected_selected": worklist.get("affected_component_selected"),
        "topology_restarts": worklist.get("topology_restart"),
        "component_recompute_count": scheduler.get("component_recompute_count"),
        "component_recompute_seconds": scheduler.get("component_recompute_seconds"),
        "component_node_visits": scheduler.get("component_node_visits"),
        "component_edge_visits": scheduler.get("component_edge_visits"),
        "component_incremental_refresh_count": scheduler.get(
            "component_incremental_refresh_count"
        ),
        "topology_change_counts": scheduler.get("topology_change_counts"),
        "provider_set_change_counts_by_family": scheduler.get(
            "provider_set_change_counts_by_family"
        ),
        "provider_set_hotspots": scheduler.get("provider_set_hotspots"),
        "top_output_owner_operations": sorted(
            (scheduler.get(
                "output_owner_creations_by_operation_family"
            ) or {}).items(),
            key=lambda item: (-item[1], item[0]),
        )[:20],
        "component_edge_update_telemetry": scheduler.get(
            "component_edge_update_telemetry"
        ),
        "top_transfer_operations": sorted(
            (scheduler.get("transfer_operation_seconds") or {}).items(),
            key=lambda item: (-item[1], item[0]),
        )[:20],
        "top_transfer_operation_counts": sorted(
            (scheduler.get("transfer_operation_counts") or {}).items(),
            key=lambda item: (-item[1], item[0]),
        )[:20],
        "top_execution_families": top_families,
        "top_family_seconds": top_family_seconds,
        "top_restart_operations": top_restart_operations,
        "top_restart_reasons": top_restart_reasons,
        "top_restart_operation_reasons": top_restart_operation_reasons,
        "trace_tail": result.get("trace_tail"),
    }
    encoded = json.dumps(report, sort_keys=True)
    if args.output_json is None:
        print(encoded)
    else:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output_json.with_suffix(args.output_json.suffix + ".tmp")
        temporary.write_text(encoded + "\n", encoding="utf-8")
        temporary.replace(args.output_json)


if __name__ == "__main__":
    main()
