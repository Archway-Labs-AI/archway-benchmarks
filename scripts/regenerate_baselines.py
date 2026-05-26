"""Regenerate TypeEvalPy baselines against CURRENT ground truth.

Runs the six deterministic baselines (HeaderGen, Jedi, Pyright, Scalpel,
Type4Py, HiTyper; plus HityperDL when cheap) through the vendored Docker
runners on both `micro-benchmark` and the frozen Autogen dataset, scores
them via `result_analyzer`, and persists each as an external-baseline run
in the harness store.

Designed for unattended execution:
  - logs to `baselines_<date>.log`
  - checkpoints `.baselines_checkpoint.json` after every (tool, benchmark)
  - never aborts on a single failure: captures the error in the checkpoint
    and the final report, then moves on to the next pair

Usage:
    python scripts/regenerate_baselines.py
    python scripts/regenerate_baselines.py --tools scalpel jedi --benchmarks micro
    python scripts/regenerate_baselines.py --resume   # skip pairs already done
    python scripts/regenerate_baselines.py --no-autogen  # skip the big set
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

from archway_benchmarks.benchmarks import (
    TypeEvalPyAutogenBenchmark,
    TypeEvalPyBenchmark,
)
from archway_benchmarks.external_baselines import RUNNER_REGISTRY, run_and_ingest


DEFAULT_TOOLS = ["scalpel", "jedi", "pyright", "headergen", "hityper", "type4py"]


@dataclass
class CheckpointEntry:
    tool: str
    benchmark: str
    status: str  # "ok" | "failed"
    run_id: int | None
    runtime_seconds: float
    image_digest: str | None
    error: str | None
    completed_at: str


def _benchmark_for(name: str):
    if name == "micro":
        return TypeEvalPyBenchmark()
    if name == "autogen":
        return TypeEvalPyAutogenBenchmark()
    raise ValueError(f"unknown benchmark name: {name}")


def _gt_commit() -> str:
    out = subprocess.check_output(
        ["git", "-C", str(REPO_ROOT / "vendor" / "TypeEvalPy"), "rev-parse", "HEAD"]
    )
    return out.decode().strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", nargs="+", default=DEFAULT_TOOLS)
    parser.add_argument(
        "--benchmarks",
        nargs="+",
        default=["micro", "autogen"],
        choices=["micro", "autogen"],
    )
    parser.add_argument("--db", default=str(REPO_ROOT / "runs.db"))
    parser.add_argument(
        "--results-root",
        default=str(REPO_ROOT / "external_results"),
        help="Root directory under which per-tool Docker results are written.",
    )
    parser.add_argument(
        "--checkpoint",
        default=str(REPO_ROOT / ".baselines_checkpoint.json"),
        help="JSON file mapping (tool, benchmark) -> outcome; resume key.",
    )
    parser.add_argument("--log", default=None)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip (tool, benchmark) pairs already marked status=ok in the checkpoint.",
    )
    parser.add_argument("--nocache", action="store_true")
    parser.add_argument(
        "--no-autogen",
        action="store_true",
        help="Skip the autogen benchmark even if listed; runtime is much longer.",
    )
    args = parser.parse_args()

    log_path = args.log or str(REPO_ROOT / f"baselines_{datetime.now().strftime('%Y%m%d-%H%M%S')}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
    )
    log = logging.getLogger("regenerate-baselines")
    log.info("commit: %s", _gt_commit())
    log.info("tools=%s benchmarks=%s", args.tools, args.benchmarks)

    bad_tools = [t for t in args.tools if t not in RUNNER_REGISTRY]
    if bad_tools:
        log.error("unknown tools: %s; choices=%s", bad_tools, list(RUNNER_REGISTRY))
        return 2

    benchmark_names = args.benchmarks
    if args.no_autogen and "autogen" in benchmark_names:
        benchmark_names = [b for b in benchmark_names if b != "autogen"]

    checkpoint_path = Path(args.checkpoint)
    checkpoint: dict[str, CheckpointEntry] = {}
    if checkpoint_path.exists():
        raw = json.loads(checkpoint_path.read_text())
        checkpoint = {k: CheckpointEntry(**v) for k, v in raw.items()}
        log.info("loaded %d prior outcomes from checkpoint", len(checkpoint))

    db_path = Path(args.db).resolve()
    results_root = Path(args.results_root).resolve()
    results_root.mkdir(parents=True, exist_ok=True)

    gt_commit = _gt_commit()

    total = len(args.tools) * len(benchmark_names)
    done = 0
    overall_start = time.monotonic()

    for benchmark_name in benchmark_names:
        bench = _benchmark_for(benchmark_name)
        log.info(
            "benchmark %s ready: %d snippets / %d annotations",
            benchmark_name,
            len(bench.load()),
            sum(len(s.annotations) for s in bench.load()),
        )
        per_bench_results = results_root / benchmark_name
        for tool in args.tools:
            done += 1
            key = f"{tool}::{benchmark_name}"
            if args.resume and key in checkpoint and checkpoint[key].status == "ok":
                log.info(
                    "[%d/%d] %s SKIP (already done as run #%d)",
                    done,
                    total,
                    key,
                    checkpoint[key].run_id,
                )
                continue

            log.info("[%d/%d] %s START", done, total, key)
            outcome = run_and_ingest(
                tool=tool,
                benchmark=bench,
                benchmark_commit=gt_commit,
                db_path=db_path,
                results_root=per_bench_results,
                nocache=args.nocache,
            )
            entry = CheckpointEntry(
                tool=tool,
                benchmark=benchmark_name,
                status="ok" if outcome.error is None else "failed",
                run_id=outcome.run_id,
                runtime_seconds=outcome.runtime_seconds,
                image_digest=outcome.image_digest,
                error=outcome.error,
                completed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            checkpoint[key] = entry
            checkpoint_path.write_text(
                json.dumps(
                    {k: asdict(v) for k, v in checkpoint.items()},
                    indent=2,
                )
                + "\n"
            )
            if outcome.error:
                log.error("[%d/%d] %s FAILED in %.1fs: %s",
                          done, total, key, outcome.runtime_seconds, outcome.error)
            else:
                log.info(
                    "[%d/%d] %s OK in %.1fs (run #%d)",
                    done,
                    total,
                    key,
                    outcome.runtime_seconds,
                    outcome.run_id,
                )

    elapsed = time.monotonic() - overall_start
    failures = [k for k, v in checkpoint.items() if v.status != "ok"]
    log.info(
        "DONE in %.0fs · %d total, %d ok, %d failed (%s)",
        elapsed,
        len(checkpoint),
        sum(1 for v in checkpoint.values() if v.status == "ok"),
        len(failures),
        ", ".join(failures) if failures else "none",
    )
    log.info("checkpoint: %s", checkpoint_path)
    log.info("log:        %s", log_path)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
