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
    parser.add_argument("--body-label")
    args = parser.parse_args()
    result = _run_successor_repo_probe(
        engine_worktree=args.engine_worktree,
        source_root=args.source_root,
        runner=("hatch", "run", "python"),
        timeout=args.timeout,
        demand_limit=args.demand_limit,
        checkpoint_roots=args.checkpoint_roots,
        body_label=args.body_label,
    )
    summary = result.get("analysis_summary") or {}
    scheduler = summary.get("scheduler") or {}
    worklist = scheduler.get("worklist_schedule_counts") or {}
    print(json.dumps({
        "ok": result.get("ok"),
        "error": result.get("error"),
        "phase_seconds": summary.get("phase_seconds"),
        "modules": summary.get("modules"),
        "observations": summary.get("observations"),
        "signature_demands": summary.get("targeted_addresses"),
        "requested_addresses": summary.get("requested_addresses"),
        "requested_body_roots": summary.get("requested_body_roots"),
        "body_profiles": summary.get("body_profiles"),
        "unique_productions": scheduler.get("unique_production_count"),
        "production_executions": scheduler.get("production_execution_count"),
        "repeated_productions": scheduler.get("repeated_production_count"),
        "affected_selected": worklist.get("affected_component_selected"),
        "topology_restarts": worklist.get("topology_restart"),
        "trace_tail": result.get("trace_tail"),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
