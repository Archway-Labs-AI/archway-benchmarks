"""Re-score existing external-baseline runs with the lenient (publication-
era) scorer and persist `scope = "all_lenient"` rows in the store.

Use this after `regenerate_baselines.py` to add comparison-friendly numbers
without re-running Docker.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from archway_benchmarks.benchmarks import (
    TypeEvalPyAutogenBenchmark,
    TypeEvalPyBenchmark,
)
from archway_benchmarks.external_baselines import parse_tool_results
from archway_benchmarks.scoring.typeevalpy_lenient import score_predictions_lenient
from archway_benchmarks.store import connect, record_scores


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(ROOT / "runs.db"))
    parser.add_argument(
        "--results-root", default=str(ROOT / "external_results")
    )
    args = parser.parse_args()

    db = Path(args.db)
    results_root = Path(args.results_root)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, engine, benchmark FROM runs WHERE engine LIKE 'external:%' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("no external runs found")
        return 0

    for r in rows:
        run_id = r["id"]
        tool = r["engine"].split(":", 1)[1]
        bench_name = r["benchmark"]
        sub = "micro" if bench_name == "typeevalpy" else "autogen"
        tool_results_dir = results_root / sub / tool
        if not tool_results_dir.exists():
            print(f"#{run_id} {tool}/{sub}: results dir missing ({tool_results_dir}); skipping")
            continue

        benchmark = (
            TypeEvalPyBenchmark()
            if bench_name == "typeevalpy"
            else TypeEvalPyAutogenBenchmark()
        )
        predictions = parse_tool_results(tool_results_dir, benchmark)
        lenient = score_predictions_lenient(benchmark, predictions)

        with connect(db) as c:
            record_scores(c, run_id, scope="all_lenient", scores=lenient)

        print(
            f"#{run_id} {tool}/{sub}: lenient exact={lenient.exact_total}/{lenient.total_annotations}"
            f" (FR={lenient.exact_by_kind.get('return',0)},"
            f" FP={lenient.exact_by_kind.get('parameter',0)},"
            f" LV={lenient.exact_by_kind.get('variable',0)})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
