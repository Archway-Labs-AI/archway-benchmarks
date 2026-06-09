"""Top-level CLI: `archway-bench run | score | export | serve | manifest`.

Engines and benchmarks are pluggable by name. Today the only benchmark is
TypeEvalPy and the only engine is the stub pair (real engines slot in via
the registries below).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

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


def _build_archway_engines(benchmark: Benchmark, accuracy: float, seed: int | None):
    """Construct the Archway engine triple. ``accuracy``/``seed`` are unused
    (kept for signature parity with the stub factory). Assumes the analysis
    dev server is running locally on its default port (``hatch run analyze``
    in ``~/Projects/Archway``)."""
    from archway_benchmarks.benchmarks.archway_adapter import ArchwayAnalysisResultAdapter
    from archway_benchmarks.engines.archway import ArchwayAnalysisEngine, ArchwayTranslationEngine

    # The analysis engine sends GET /types?module=main.py&root=<abs_snippet_dir>
    # — it resolves Snippet.file_path (suite-relative) against this corpus root.
    corpus_root = getattr(benchmark, "corpus_root", None)
    return (
        ArchwayTranslationEngine(),
        ArchwayAnalysisEngine(corpus_root=corpus_root),
        ArchwayAnalysisResultAdapter(),
    )


ENGINES: dict[
    str,
    Callable[[Benchmark, float, int | None], tuple[TranslationEngine, AnalysisEngine, object]],
] = {
    "stub": _build_stub_engines,
    "archway": _build_archway_engines,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="archway-bench")
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="Run a benchmark end-to-end and persist a run")
    p_run.add_argument("--benchmark", default="typeevalpy", choices=list(BENCHMARKS))
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

    p_iter = sub.add_parser(
        "iterate",
        help="One-shot: restart the Archway analysis server, run the harness, update the progress report, stop the server. The lifecycle wrap ensures every run uses freshly loaded analysis code — no staleness from the long-running server holding pre-edit modules.",
    )
    p_iter.add_argument("--archway-dir", default=os.environ.get("ARCHWAY_DIR", os.path.expanduser("~/Projects/Archway")),
                        help="Archway repo (default: $ARCHWAY_DIR or ~/Projects/Archway).")
    p_iter.add_argument("--repo-root",
                        default=os.environ.get("ARCHWAY_ANALYZE_REPO_ROOT", "/Users/benoconnor/Projects/archRepos/TypeEvalPy/micro-benchmark"),
                        help="Benchmark repo root the analysis server resolves modules under.")
    p_iter.add_argument("--port", type=int, default=int(os.environ.get("ARCHWAY_ANALYZE_PORT", "8788")))
    p_iter.add_argument("--server-log", default="/tmp/archway_analyze.log")
    p_iter.add_argument("--benchmark", default="typeevalpy", choices=list(BENCHMARKS))
    p_iter.add_argument("--db", default="runs.db")
    p_iter.add_argument("--notes", default=None)
    p_iter.add_argument("--out-md", default="archway_progress.md",
                        help="Path for the markdown progress report (empty string to skip).")
    p_iter.add_argument(
        "--detail", action="store_true",
        help="Also write a per-run detail report (outcomes, categories, TYPE_MISS patterns, translation errors) to archway_report_run<N>.md.",
    )
    p_iter.add_argument(
        "--detail-full", action="store_true",
        help="With --detail, include the full per-annotation non-EXACT listing.",
    )

    p_progress = sub.add_parser(
        "progress",
        help="Show recent runs with score deltas — for tracking iterative improvements.",
    )
    p_progress.add_argument(
        "--engine",
        default="archway",
        help="Engine prefix to filter on (default: archway). Pass empty string for all runs.",
    )
    p_progress.add_argument("--limit", type=int, default=5, help="Number of recent runs to show on stdout (the markdown report always includes the full history).")
    p_progress.add_argument("--db", default="runs.db")
    p_progress.add_argument(
        "--out-md",
        default=None,
        help="If set, also write a Markdown progress report (full history) to this path.",
    )

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
        help="Write baselines_<date>.md and .json summarising the regenerated runs.",
    )
    p_report.add_argument("--db", default="runs.db")
    p_report.add_argument("--out-md", default=None)
    p_report.add_argument("--out-json", default=None)

    p_run_report = sub.add_parser(
        "report",
        help="Write a per-run detail report (outcomes, categories, TYPE_MISS patterns, translation errors).",
    )
    p_run_report.add_argument(
        "run_id", type=int, nargs="?",
        help="Run id to report on. Defaults to the most recent run in the store.",
    )
    p_run_report.add_argument("--db", default="runs.db")
    p_run_report.add_argument(
        "--out-md", default=None,
        help="Output path (default: archway_report_run<N>.md in cwd).",
    )
    p_run_report.add_argument(
        "--full", action="store_true",
        help="Include the full per-annotation non-EXACT listing (can be long).",
    )

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
    if args.cmd == "iterate":
        return _cmd_iterate(args)
    if args.cmd == "progress":
        return _cmd_progress(args)
    if args.cmd == "regenerate-baselines":
        return _cmd_regenerate(args)
    if args.cmd == "baselines-report":
        return _cmd_report(args)
    if args.cmd == "report":
        return _cmd_run_report(args)
    parser.print_help()
    return 1


def _cmd_run(args) -> int:
    bench = BENCHMARKS[args.benchmark]()
    translator, analyzer, adapter = ENGINES[args.engine](
        bench, args.stub_accuracy, args.seed
    )
    result = run_pipeline(
        benchmark=bench,
        translator=translator,
        analyzer=analyzer,
        adapter=adapter,
        stub_accuracy=args.stub_accuracy,
        seed=args.seed,
        notes=args.notes,
        db_path=Path(args.db),
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


def _cmd_iterate(args) -> int:
    """One-shot: restart the analysis server, run, write progress, stop the server.

    The point of the lifecycle wrap is to guarantee every run uses freshly
    loaded analysis code. A long-running server holds Python module state
    in memory, so source edits made after server start aren't reflected in
    its responses — that's the staleness we've already been bitten by.
    Killing + restarting before each run is the simple, reliable answer.
    """

    def _server_pid() -> int | None:
        try:
            out = subprocess.check_output(
                ["lsof", "-ti", f":{args.port}"], stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError:
            return None
        for line in out.decode().splitlines():
            line = line.strip()
            if line:
                try:
                    return int(line.split()[0])
                except ValueError:
                    pass
        return None

    def _kill_server() -> None:
        pid = _server_pid()
        if pid is None:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        for _ in range(50):  # ~5s
            if _server_pid() is None:
                return
            time.sleep(0.1)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _start_server() -> subprocess.Popen:
        log = open(args.server_log, "w")
        proc = subprocess.Popen(
            ["hatch", "run", "analyze", "--repo-root", args.repo_root, "--port", str(args.port)],
            cwd=args.archway_dir,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        url = f"http://localhost:{args.port}/health"
        for _ in range(150):  # ~30s
            try:
                with urllib.request.urlopen(url, timeout=1) as r:
                    if r.status == 200:
                        return proc
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            if proc.poll() is not None:
                raise RuntimeError(
                    f"analyze server exited before becoming ready (rc={proc.returncode}); "
                    f"see {args.server_log}"
                )
            time.sleep(0.2)
        proc.terminate()
        raise RuntimeError(f"analyze server didn't become healthy in 30s; see {args.server_log}")

    print(f"[iterate] stopping any server on :{args.port}", flush=True)
    _kill_server()
    print(f"[iterate] starting fresh server (repo-root: {args.repo_root})", flush=True)
    _start_server()

    rc = 0
    try:
        bench = BENCHMARKS[args.benchmark]()
        translator, analyzer, adapter = ENGINES["archway"](bench, 0.0, None)
        print(f"[iterate] running {args.benchmark} / archway", flush=True)
        result = run_pipeline(
            benchmark=bench,
            translator=translator,
            analyzer=analyzer,
            adapter=adapter,
            stub_accuracy=0.0,
            seed=None,
            notes=args.notes,
            db_path=Path(args.db),
        )
        a = result.all_scores
        print(
            f"[iterate] run #{result.run_id}  "
            f"exact {a.exact_total}/{a.total_annotations} "
            f"({a.exact_total / a.total_annotations:.1%})  "
            f"processed {a.files_processed}/{a.total_snippets}  "
            f"sound {a.files_sound}/{a.total_snippets}  "
            f"complete {a.files_complete}/{a.total_snippets}",
            flush=True,
        )

        if args.out_md:
            print(f"[iterate] writing progress to {args.out_md}", flush=True)
            progress_args = argparse.Namespace(
                engine="archway", limit=5, db=args.db, out_md=args.out_md,
            )
            _cmd_progress(progress_args)

        if args.detail:
            from archway_benchmarks.reports import write_report
            detail_path = f"archway_report_run{result.run_id}.md"
            print(f"[iterate] writing detail report to {detail_path}", flush=True)
            write_report(args.db, result.run_id, detail_path, include_miss_listing=args.detail_full)
    except Exception as e:
        print(f"[iterate] failed: {type(e).__name__}: {e}", file=sys.stderr)
        rc = 1
    finally:
        print(f"[iterate] stopping server", flush=True)
        _kill_server()

    return rc


def _cmd_progress(args) -> int:
    """List recent runs (newest first) with score deltas vs the previous run.

    Defaults to the ``archway`` engine. Stdout shows the most recent
    ``--limit`` runs (one line each) for terminal use; ``--out-md`` writes
    a committable Markdown report containing the full history.
    """
    with connect(Path(args.db)) as conn:
        runs = list_runs(conn)
        prefix = args.engine.lower().strip()
        if prefix:
            runs = [r for r in runs if r.engine.lower().startswith(prefix)]
        if not runs:
            label = f"engine prefix {args.engine!r}" if prefix else "any engine"
            print(f"(no runs found for {label} in {args.db})")
            return 0
        scores_by_run = {r.id: get_scores(conn, r.id) for r in runs}

    deltas = _compute_progress_deltas(runs, scores_by_run)

    # stdout: most recent --limit runs, one line each
    for r in runs[: args.limit]:
        print(_progress_line(r, scores_by_run, deltas))

    if args.out_md:
        out_path = Path(args.out_md)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_progress_markdown(runs, scores_by_run, deltas, args.engine))
        print(f"\nwrote {out_path}")
    return 0


def _compute_progress_deltas(runs, scores_by_run):
    """For each run id, deltas (exact, files_processed) vs the next-older run."""
    chronological = list(reversed(runs))  # oldest -> newest
    prev_exact = prev_proc = None
    deltas: dict[int, tuple[int | None, int | None]] = {}
    for r in chronological:
        sc = scores_by_run.get(r.id, {}).get("all")
        ex = sc["exact_total"] if sc else None
        fp = sc.get("files_processed") if sc else None
        dx = (ex - prev_exact) if (ex is not None and prev_exact is not None) else None
        dp = (fp - prev_proc) if (fp is not None and prev_proc is not None) else None
        deltas[r.id] = (dx, dp)
        if ex is not None:
            prev_exact = ex
        if fp is not None:
            prev_proc = fp
    return deltas


def _progress_line(r, scores_by_run, deltas) -> str:
    sc = scores_by_run.get(r.id, {}).get("all")
    if not sc:
        return f"#{r.id:<3}  {r.created_at[:19]}  (no scores stored)"
    dx, dp = deltas.get(r.id, (None, None))
    dx_s = f" ({dx:+d})" if dx is not None else ""
    dp_s = f" ({dp:+d})" if dp is not None else ""
    note = f'  "{r.notes}"' if r.notes else ""
    fp = sc.get("files_processed")
    proc_s = f"  processed {fp}/{sc['total_snippets']}{dp_s}" if fp is not None else ""
    return (
        f"#{r.id:<3}  {r.created_at[:19]}  "
        f"exact {sc['exact_total']}/{sc['total_annotations']}{dx_s}{proc_s}  "
        f"sound {sc['files_sound']}/{sc['total_snippets']}  "
        f"complete {sc['files_complete']}/{sc['total_snippets']}{note}"
    )


def _progress_markdown(runs, scores_by_run, deltas, engine_filter: str) -> str:
    """Render the progress report as Markdown. Full history, newest-first."""
    from datetime import datetime, timezone

    lines: list[str] = ["# Archway on TypeEvalPy — Progress", ""]
    # Headline: most recent run with scores
    latest = next((r for r in runs if scores_by_run.get(r.id, {}).get("all")), None)
    if latest is not None:
        sc = scores_by_run[latest.id]["all"]
        pct = sc["exact_total"] / sc["total_annotations"] * 100 if sc["total_annotations"] else 0.0
        fp = sc.get("files_processed")
        proc_part = f" · {fp} / {sc['total_snippets']} files processed" if fp is not None else ""
        lines.append(
            f"**Current:** {sc['exact_total']} / {sc['total_annotations']} exact ({pct:.1f}%)"
            f"{proc_part}"
            f" · {sc['files_sound']} / {sc['total_snippets']} sound"
            f" · {sc['files_complete']} / {sc['total_snippets']} complete"
            f" · run #{latest.id} ({latest.created_at[:19]})"
        )
        lines.append("")
    label = engine_filter if engine_filter.strip() else "(all engines)"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"_Engine filter: `{label}` · Last updated {now}_")
    lines.append("")
    lines.append("## History")
    lines.append("")
    lines.append(
        "_Columns: **Exact** = annotations matching GT type set; "
        "**Processed** = files where the analysis emitted predictions (didn't error); "
        "**Sound** = files where every GT entry was answered correctly (full coverage); "
        "**Complete** = files where every prediction was correct (no wrong types). "
        "Note: Complete is inflated by errored files producing zero predictions, which "
        "vacuously satisfy the metric._"
    )
    lines.append("")
    lines.append("| # | Created | Exact | Δ | Processed | Δ | Sound | Complete | Notes |")
    lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---|")
    escape_pipe = "\\|"
    for r in runs:
        sc = scores_by_run.get(r.id, {}).get("all")
        notes_raw = r.notes or ("_(no scores stored)_" if not sc else "_(no notes)_")
        note = notes_raw.replace("|", escape_pipe)
        if not sc:
            lines.append(
                f"| {r.id} | {r.created_at[:19]} | — | — | — | — | — | — | {note} |"
            )
            continue
        dx, dp = deltas.get(r.id, (None, None))
        dx_s = f"{dx:+d}" if dx is not None else "—"
        dp_s = f"{dp:+d}" if dp is not None else "—"
        fp = sc.get("files_processed")
        proc_s = f"{fp}/{sc['total_snippets']}" if fp is not None else "—"
        lines.append(
            f"| {r.id} | {r.created_at[:19]} | "
            f"{sc['exact_total']}/{sc['total_annotations']} | {dx_s} | "
            f"{proc_s} | {dp_s} | "
            f"{sc['files_sound']}/{sc['total_snippets']} | "
            f"{sc['files_complete']}/{sc['total_snippets']} | {note} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


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


def _cmd_run_report(args) -> int:
    from archway_benchmarks.reports import write_report
    from archway_benchmarks.store import connect

    run_id = args.run_id
    if run_id is None:
        with connect(Path(args.db)) as conn:
            row = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                print("no runs in store", file=sys.stderr)
                return 1
            run_id = row[0]
    out_md = args.out_md or f"archway_report_run{run_id}.md"
    out = write_report(args.db, run_id, out_md, include_miss_listing=args.full)
    print(f"wrote {out}")
    return 0


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
