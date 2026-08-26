"""Top-level CLI: `archway-bench run | score | runs | export | serve | manifest | regenerate-baselines | baselines-report` (plus `bugsinpy-*`).

Engines and benchmarks are pluggable by name. The harness ships a stub backend
that exercises the full pipeline without requiring a real analysis engine.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

from archway_benchmarks import bugsinpy_cli
from archway_benchmarks.benchmarks import TypeEvalPyAutogenBenchmark, TypeEvalPyBenchmark
from archway_benchmarks.benchmarks.base import Benchmark
from archway_benchmarks.engines.base import AnalysisEngine, TranslationEngine
from archway_benchmarks.engines.stubs import make_stub_pair
from archway_benchmarks.outcome import Outcome
from archway_benchmarks.runner import run as run_pipeline
from archway_benchmarks.store import connect, get_scores, list_annotations, list_runs


BENCHMARKS: dict[str, Callable[[], Benchmark]] = {
    "typeevalpy": TypeEvalPyBenchmark,
    "typeevalpy_autogen": TypeEvalPyAutogenBenchmark,
}


def _build_stub_engines(benchmark: Benchmark, accuracy: float, seed: int | None):
    snippets = benchmark.load()
    translator, analyzer, adapter = make_stub_pair(snippets, accuracy=accuracy, seed=seed)
    return translator, analyzer, adapter


def _build_successor_engines(
    benchmark: Benchmark,
    accuracy: float,
    seed: int | None,
):
    """Construct the in-process diagram-only successor engine triple."""

    from archway_benchmarks.engines.archway import ArchwayTranslationEngine
    from archway_benchmarks.engines.successor_archway import (
        SuccessorArchwayAnalysisEngine,
        SuccessorTypeEvalPyAdapter,
    )

    return (
        ArchwayTranslationEngine(
            corpus_root=getattr(benchmark, "corpus_root", None),
            dependency_roots=tuple(
                getattr(benchmark, "dependency_roots", ())
            ),
        ),
        SuccessorArchwayAnalysisEngine(record_events=False),
        SuccessorTypeEvalPyAdapter(),
    )


ENGINES: dict[
    str,
    Callable[[Benchmark, float, int | None], tuple[TranslationEngine, AnalysisEngine, object]],
] = {
    "stub": _build_stub_engines,
    "successor": _build_successor_engines,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="archway-bench")
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="Run a benchmark end-to-end and persist a run")
    p_run.add_argument("--benchmark", default="typeevalpy", choices=list(BENCHMARKS))
    p_run.add_argument(
        "--corpus-root",
        default=None,
        help="Explicit benchmark corpus root; recorded workflows should not rely on checkout-relative discovery.",
    )
    p_run.add_argument("--engine", default="stub", choices=list(ENGINES))
    p_run.add_argument("--stub-accuracy", type=float, default=0.67)
    p_run.add_argument("--seed", type=int, default=None)
    p_run.add_argument("--db", default="runs.db", help="Path to SQLite store")
    p_run.add_argument("--notes", default=None)

    p_score = sub.add_parser("score", help="Print stored scores for a run")
    p_score.add_argument("run_id", type=int)
    p_score.add_argument("--db", default="runs.db")

    p_runs = sub.add_parser("runs", help="List stored runs")
    p_runs.add_argument("--db", default="runs.db")

    p_export = sub.add_parser(
        "export",
        help="Emit predictions in TypeEvalPy tool-output format (per-snippet JSON)",
    )
    p_export.add_argument("run_id", type=int)
    p_export.add_argument("--db", default="runs.db")
    p_export.add_argument(
        "--output-dir",
        default="export",
        help="Directory to write <suite>/main_result.json files",
    )

    p_serve = sub.add_parser("serve", help="Start the inspector dashboard")
    p_serve.add_argument("--db", default="runs.db")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8088)

    p_manifest = sub.add_parser("manifest", help="Regenerate the corpus manifest")
    p_manifest.add_argument("--output", "-o", default="corpus_manifest.json")

    # BugsInPy (parallel benchmark): bugsinpy-manifest|detect|repair|progress.
    bugsinpy_cli.register(sub)

    p_regen = sub.add_parser(
        "regenerate-baselines",
        help="Re-run published baselines against the current GT (Phase 1 work).",
        description=(
            "Builds each tool's Docker image (via extras/TypeEvalPy/src/runner_class),"
            " runs it on the named benchmark(s), scores with result_analyzer, and"
            " persists each result as an external-baseline run in the store."
        ),
    )
    p_regen.add_argument("--tools", nargs="+", default=None)
    p_regen.add_argument(
        "--benchmarks", nargs="+", default=None, choices=["micro", "autogen"]
    )
    p_regen.add_argument("--db", default="runs.db")
    p_regen.add_argument("--results-root", default="external_results")
    p_regen.add_argument("--checkpoint", default=".baselines_checkpoint.json")
    p_regen.add_argument("--log", default=None)
    p_regen.add_argument("--resume", action="store_true")
    p_regen.add_argument("--nocache", action="store_true")
    p_regen.add_argument("--no-autogen", action="store_true")

    p_report = sub.add_parser(
        "baselines-report",
        help="Write leaderboard/baselines.{md,json} summarising the regenerated runs.",
    )
    p_report.add_argument("--db", default="runs.db")
    p_report.add_argument("--out-md", default=None)
    p_report.add_argument("--out-json", default=None)

    args = parser.parse_args(argv)

    if args.cmd is None:
        parser.print_help()
        return 0
    if args.cmd == "run":
        return _cmd_run(args)
    if args.cmd == "score":
        return _cmd_score(args)
    if args.cmd == "runs":
        return _cmd_runs(args)
    if args.cmd == "export":
        return _cmd_export(args)
    if args.cmd == "serve":
        return _cmd_serve(args)
    if args.cmd == "manifest":
        return _cmd_manifest(args)
    bugsinpy_rv = bugsinpy_cli.dispatch(args)
    if bugsinpy_rv is not None:
        return bugsinpy_rv
    if args.cmd == "regenerate-baselines":
        return _cmd_regenerate(args)
    if args.cmd == "baselines-report":
        return _cmd_report(args)
    parser.print_help()
    return 1


def _cmd_run(args) -> int:
    bench = BENCHMARKS[args.benchmark](
        **(
            {"corpus_root": Path(args.corpus_root)}
            if args.corpus_root else {}
        )
    )
    metadata = None
    translator, analyzer, adapter = ENGINES[args.engine](
        bench, args.stub_accuracy, args.seed
    )
    if args.engine == "successor":
        metadata = {
            "analysis_surface": "diagram-only",
            "record_events": False,
            "session_policy": "persistent-forward-then-targeted",
        }
    result = run_pipeline(
        benchmark=bench,
        translator=translator,
        analyzer=analyzer,
        adapter=adapter,
        stub_accuracy=args.stub_accuracy,
        seed=args.seed,
        notes=args.notes,
        db_path=Path(args.db),
        metadata=metadata,
    )
    a = result.all_scores
    c = result.covered_scores
    print(f"run id: {result.run_id}")
    print(
        f"  all     -> exact {a.exact_total}/{a.total_annotations} "
        f"({a.exact_total / a.total_annotations:.1%})  "
        f"processed {a.files_processed}/{a.total_snippets}  "
        f"sound {a.files_sound}/{a.total_snippets}  "
        f"complete {a.files_complete}/{a.total_snippets}"
    )
    print(
        f"  covered -> exact {c.exact_total}/{c.total_annotations} "
        f"({c.exact_total / c.total_annotations if c.total_annotations else 0:.1%})  "
        f"processed {c.files_processed}/{c.total_snippets}  "
        f"sound {c.files_sound}/{c.total_snippets}  "
        f"complete {c.files_complete}/{c.total_snippets}"
    )
    return 0


def _cmd_score(args) -> int:
    with connect(Path(args.db)) as conn:
        scores = get_scores(conn, args.run_id)
        if not scores:
            print(f"no run {args.run_id} in {args.db}", file=sys.stderr)
            return 1
        for scope, row in scores.items():
            print(
                f"[{scope}] exact {row['exact_total']}/{row['total_annotations']}  "
                f"sound {row['files_sound']}/{row['total_snippets']}  "
                f"complete {row['files_complete']}/{row['total_snippets']}  "
                f"precision {row['annotation_precision']:.3f}  "
                f"recall {row['annotation_recall']:.3f}"
            )
    return 0


def _cmd_runs(args) -> int:
    with connect(Path(args.db)) as conn:
        rows = list_runs(conn)
        if not rows:
            print("(no runs)")
            return 0
        for r in rows:
            print(
                f"#{r.id}  {r.created_at}  {r.benchmark}/{r.engine}  "
                f"stub={r.stub_accuracy}  seed={r.seed}"
            )
    return 0


def _cmd_export(args) -> int:
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with connect(Path(args.db)) as conn:
        anns = list_annotations(conn, args.run_id)
        emitted = list_annotations(conn, args.run_id, outcome=Outcome.EXACT)
        emitted += list_annotations(conn, args.run_id, outcome=Outcome.TYPE_MISS)
        # SPURIOUS rows are in a separate table; pull them too.
        from archway_benchmarks.store import list_spurious

        spurious_rows = list_spurious(conn, args.run_id)

    grouped: dict[str, list[dict]] = {}
    for r in emitted:
        if r["predicted_types"] is None:
            continue
        grouped.setdefault(r["suite_path"], []).append(_db_row_to_record(r))
    for r in spurious_rows:
        grouped.setdefault(r["suite_path"], []).append(_db_row_to_record(r, spurious=True))

    count = 0
    for suite_path, records in grouped.items():
        target = out_dir / suite_path
        target.mkdir(parents=True, exist_ok=True)
        (target / "main_result.json").write_text(json.dumps(records, indent=2) + "\n")
        count += 1
    print(f"exported {count} snippet results under {out_dir}/  (run {args.run_id})")
    print(f"  {len(anns)} GT-keyed predictions, {len(spurious_rows)} spurious")
    return 0


def _db_row_to_record(row: dict, *, spurious: bool = False) -> dict:
    types_raw = row["predicted_types"]
    types = json.loads(types_raw) if types_raw else []
    rec: dict = {
        "file": "main.py",
        "line_number": row["line"],
        "col_offset": row["col"],
        "type": types,
    }
    kind = row["kind"]
    name = row["name"]
    function = row["function"]
    if kind == "return":
        rec["function"] = name
    elif kind == "parameter":
        rec["function"] = function
        rec["parameter"] = name
    elif kind == "variable":
        if function:
            rec["function"] = function
        rec["variable"] = name
    return rec


def _cmd_serve(args) -> int:
    try:
        from archway_benchmarks.dashboard.server import serve
    except ImportError as e:
        print(f"dashboard dependencies missing: {e}", file=sys.stderr)
        print("install with: pip install '.[dashboard]'", file=sys.stderr)
        return 1
    serve(db_path=Path(args.db), host=args.host, port=args.port)
    return 0


def _cmd_manifest(args) -> int:
    from archway_benchmarks.manifest import _cli

    return _cli(["--output", args.output])


def _cmd_regenerate(args) -> int:
    cmd_argv: list[str] = []
    if args.tools:
        cmd_argv += ["--tools", *args.tools]
    if args.benchmarks:
        cmd_argv += ["--benchmarks", *args.benchmarks]
    cmd_argv += ["--db", args.db, "--results-root", args.results_root, "--checkpoint", args.checkpoint]
    if args.log:
        cmd_argv += ["--log", args.log]
    if args.resume:
        cmd_argv.append("--resume")
    if args.nocache:
        cmd_argv.append("--nocache")
    if args.no_autogen:
        cmd_argv.append("--no-autogen")
    # Shell out so we get the same flag-parsing as direct script invocation.
    import subprocess

    script = Path(__file__).resolve().parents[2] / "scripts" / "regenerate_baselines.py"
    return subprocess.call([sys.executable, str(script), *cmd_argv])


def _cmd_report(args) -> int:
    from archway_benchmarks.baselines_report import _cli

    cmd: list[str] = ["--db", args.db]
    if args.out_md:
        cmd += ["--out-md", args.out_md]
    if args.out_json:
        cmd += ["--out-json", args.out_json]
    return _cli(cmd)


if __name__ == "__main__":
    sys.exit(main())
