"""Dashboard + inspector — FastAPI app in the Archway brand.

Routes:
  /                              runs list
  /runs/{id}                     scores view (us vs leaderboard, both scopes)
  /runs/{id}/inspect             corpus annotation table + filters
  /runs/{id}/snippets/{path}     per-snippet inspector (source + outcomes)
  /runs/{id}/targets             FP + callable target-set board
  /runs/{id}/compare/{other}     run-compare (flipped annotations)
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from archway_benchmarks.leaderboard import (
    RegeneratedLeaderboard,
    StaticLeaderboard,
)
from archway_benchmarks.outcome import Outcome
from archway_benchmarks.store import (
    connect,
    get_run,
    get_scores,
    list_annotations,
    list_runs,
    list_snippets,
    list_spurious,
)

_DASHBOARD_DIR = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_DASHBOARD_DIR / "templates"))


def build_app(db_path: Path) -> FastAPI:
    app = FastAPI(title="Archway Benchmarks")
    app.mount(
        "/static",
        StaticFiles(directory=str(_DASHBOARD_DIR / "static")),
        name="static",
    )

    leaderboard = StaticLeaderboard()
    regenerated = RegeneratedLeaderboard(db_path)

    def _render(request: Request, name: str, **ctx: Any) -> Any:
        return _TEMPLATES.TemplateResponse(request=request, name=name, context=ctx)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Any:
        with connect(db_path) as conn:
            runs = list_runs(conn)
        return _render(request, "runs.html", runs=runs, db_path=str(db_path))

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_scores(request: Request, run_id: int) -> Any:
        with connect(db_path) as conn:
            run = get_run(conn, run_id)
            if not run:
                raise HTTPException(404, f"no run {run_id}")
            scores = get_scores(conn, run_id)
        for _scope, row in scores.items():
            row["exact_by_kind"] = json.loads(row["exact_by_kind_json"])
            row["exact_by_category"] = json.loads(row["exact_by_category_json"])
            row["exact_by_bucket_kind"] = (
                json.loads(row["exact_by_bucket_kind_json"])
                if row.get("exact_by_bucket_kind_json")
                else None
            )
        snap_static = leaderboard.get(run.benchmark)
        snap_regen = regenerated.get(run.benchmark)
        regen_by_tool = {
            e.tool.lower(): e for e in (snap_regen.tools if snap_regen else ())
        }
        # GT bucket × kind totals (denominators for the scoreboard).
        bench_totals: dict[str, dict[str, int]] | None = None
        try:
            from archway_benchmarks.benchmarks import (
                TypeEvalPyAutogenBenchmark,
                TypeEvalPyBenchmark,
            )
            bench = (
                TypeEvalPyAutogenBenchmark()
                if run.benchmark == "typeevalpy_autogen"
                else TypeEvalPyBenchmark()
            )
            bench_totals = bench.gt_bucket_kind_totals()
        except Exception:  # noqa: BLE001
            bench_totals = None
        from archway_benchmarks.rule_buckets import BUCKETS, BUCKET_LABELS
        return _render(
            request,
            "scores.html",
            run=run,
            scores=scores,
            leaderboard=snap_static,
            regenerated=snap_regen,
            regen_by_tool=regen_by_tool,
            gt_bucket_totals=bench_totals,
            bucket_order=BUCKETS,
            bucket_labels=BUCKET_LABELS,
        )

    @app.get("/runs/{run_id}/inspect", response_class=HTMLResponse)
    def inspect(
        request: Request,
        run_id: int,
        category: str | None = None,
        kind: str | None = None,
        outcome: str | None = None,
        fp_only: int = 0,
        callable_only: int = 0,
    ) -> Any:
        with connect(db_path) as conn:
            run = get_run(conn, run_id)
            if not run:
                raise HTTPException(404)
            anns = list_annotations(
                conn,
                run_id,
                outcome=Outcome(outcome) if outcome else None,
                category=category or None,
                kind=kind or None,
                only_function_parameter=bool(fp_only),
                only_callable_gt=bool(callable_only),
            )
        return _render(
            request,
            "inspect.html",
            run=run,
            annotations=anns,
            filters={
                "category": category or "",
                "kind": kind or "",
                "outcome": outcome or "",
                "fp_only": fp_only,
                "callable_only": callable_only,
            },
        )

    @app.get("/runs/{run_id}/snippets/{path:path}", response_class=HTMLResponse)
    def snippet_view(request: Request, run_id: int, path: str) -> Any:
        with connect(db_path) as conn:
            run = get_run(conn, run_id)
            if not run:
                raise HTTPException(404)
            rows = list_snippets(conn, run_id)
            snippet = next((r for r in rows if r["suite_path"] == path), None)
            if not snippet:
                raise HTTPException(404, f"no snippet {path} in run {run_id}")
            anns = [a for a in list_annotations(conn, run_id) if a["suite_path"] == path]
            spur = [s for s in list_spurious(conn, run_id) if s["suite_path"] == path]

        lines = snippet["source"].splitlines() or [""]
        marks_by_line: dict[int, list[dict]] = defaultdict(list)
        for a in anns:
            marks_by_line[a["line"]].append(a)

        return _render(
            request,
            "snippet.html",
            run=run,
            snippet=snippet,
            annotations=anns,
            spurious=spur,
            lines=list(enumerate(lines, start=1)),
            marks_by_line=marks_by_line,
        )

    @app.get("/runs/{run_id}/targets", response_class=HTMLResponse)
    def targets(request: Request, run_id: int) -> Any:
        with connect(db_path) as conn:
            run = get_run(conn, run_id)
            if not run:
                raise HTTPException(404)
            fp_total = len(list_annotations(conn, run_id, only_function_parameter=True))
            fp_exact = len(
                list_annotations(
                    conn, run_id, only_function_parameter=True, outcome=Outcome.EXACT
                )
            )
            call_total = len(list_annotations(conn, run_id, only_callable_gt=True))
            call_exact = len(
                list_annotations(conn, run_id, only_callable_gt=True, outcome=Outcome.EXACT)
            )
        snap = leaderboard.get(run.benchmark)
        # Field's near-zero baselines (paper_table_1.csv columns) -- best per slice.
        fp_field_best = max(t.function_parameters for t in snap.tools)
        return _render(
            request,
            "targets.html",
            run=run,
            fp_total=fp_total,
            fp_exact=fp_exact,
            callable_total=call_total,
            callable_exact=call_exact,
            fp_field_best=fp_field_best,
        )

    @app.get("/runs/{run_id}/compare/{other_id}", response_class=HTMLResponse)
    def compare(request: Request, run_id: int, other_id: int) -> Any:
        with connect(db_path) as conn:
            run_a = get_run(conn, run_id)
            run_b = get_run(conn, other_id)
            if not run_a or not run_b:
                raise HTTPException(404)
            anns_a = list_annotations(conn, run_id)
            anns_b = list_annotations(conn, other_id)
            scores_a = get_scores(conn, run_id)
            scores_b = get_scores(conn, other_id)

        def key(a: dict) -> tuple:
            return (a["suite_path"], a["line"], a["col"], a["kind"], a["name"], a["function"] or "")

        a_by_key = {key(a): a for a in anns_a}
        b_by_key = {key(b): b for b in anns_b}
        common = sorted(set(a_by_key) & set(b_by_key))

        flipped: list[dict] = []
        for k in common:
            a = a_by_key[k]
            b = b_by_key[k]
            if a["outcome"] != b["outcome"]:
                flipped.append({"a": a, "b": b})

        gained_exact = [r for r in flipped if r["b"]["outcome"] == Outcome.EXACT.value]
        lost_exact = [r for r in flipped if r["a"]["outcome"] == Outcome.EXACT.value]

        return _render(
            request,
            "compare.html",
            run_a=run_a,
            run_b=run_b,
            scores_a=scores_a,
            scores_b=scores_b,
            gained_exact=gained_exact,
            lost_exact=lost_exact,
            flipped=flipped,
        )

    return app


def serve(db_path: Path, host: str = "127.0.0.1", port: int = 8088) -> None:
    import uvicorn

    app = build_app(db_path)
    uvicorn.run(app, host=host, port=port, log_level="info")
