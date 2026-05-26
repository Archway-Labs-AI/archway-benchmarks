"""Audit test: confirms the four-outcome + dual-scope scoring substrate
exists on the **internal** Archway path (not the upstream tool's path).

If this test passes you can trust that:

  - Every GT annotation lands in exactly one of
    `{EXACT, TYPE_MISS, LOCATION_MISS}` per run.
  - Predictions outside GT keys are tracked as `SPURIOUS`.
  - Two `Scores` rows are persisted per run: one keyed
    `scope = "all"` (leaderboard-comparable, missing snippets count as
    LOCATION_MISS) and one keyed `scope = "covered"` (restricted to
    snippets the translation engine attempted).
  - The covered subset's size is queryable from the store.

Failure here means Ben's first real plug-in produces uninterpretable numbers.
"""
from __future__ import annotations

from archway_benchmarks.benchmarks import TypeEvalPyBenchmark
from archway_benchmarks.benchmarks.typeevalpy import _location_to_record
from archway_benchmarks.coverage import CoverageStatus, UnsupportedSourceError
from archway_benchmarks.engines.base import AnalysisEngine, TranslationEngine
from archway_benchmarks.engines.stubs import (
    StubAnalysisResult,
    StubTranslation,
    StubTranslationEngine,
)
from archway_benchmarks.benchmarks.stub_adapter import StubAnalysisResultAdapter
from archway_benchmarks.outcome import Outcome
from archway_benchmarks.runner import run
from archway_benchmarks.scoring import score_snippet
from archway_benchmarks.store import connect, get_scores, list_annotations, list_spurious
from archway_benchmarks.types import Annotation, Location


def _loc(line, col, kind, name, function=None, file="m.py"):
    return Location(file=file, line=line, col=col, kind=kind, name=name, function=function)


def test_four_outcome_buckets_classified_on_internal_path():
    """Single deterministic scoring call must produce one of each bucket."""
    gt = {
        _loc(1, 0, "return", "perfect"): frozenset({"int"}),
        _loc(2, 0, "return", "wrong_type"): frozenset({"int"}),
        _loc(3, 0, "return", "missing"): frozenset({"int"}),
    }
    predictions = {
        _loc(1, 0, "return", "perfect"): frozenset({"int"}),          # EXACT
        _loc(2, 0, "return", "wrong_type"): frozenset({"str"}),       # TYPE_MISS
        # _loc(3, ...) deliberately absent                             # LOCATION_MISS
        _loc(99, 0, "variable", "ghost"): frozenset({"int"}),         # SPURIOUS
    }
    s = score_snippet("dummy", gt, predictions, _location_to_record)
    buckets = {o.outcome for o in s.outcomes}
    assert Outcome.EXACT in buckets
    assert Outcome.TYPE_MISS in buckets
    assert Outcome.LOCATION_MISS in buckets
    assert len(s.spurious_predictions) == 1, s.spurious_predictions


def test_store_persists_per_annotation_outcomes_and_dual_scopes(tmp_path):
    """End-to-end: real Runner.run on the real benchmark, then prove the
    store has per-annotation outcomes and two `scores` rows with distinct
    sizes when half the corpus is marked UNSUPPORTED."""
    db = tmp_path / "audit.db"
    bench = TypeEvalPyBenchmark()
    snippets = bench.load()

    # Build the stub trio (engines opaque to the rest of the harness).
    from archway_benchmarks.engines.stubs import make_stub_pair
    translator, analyzer, adapter = make_stub_pair(snippets, accuracy=0.7, seed=11)

    # Mark half the snippets UNSUPPORTED to exercise the dual-scope path.
    excluded = {s.suite_path for s in snippets[: len(snippets) // 2]}

    def probe(snip):
        return (
            CoverageStatus.UNSUPPORTED if snip.suite_path in excluded else CoverageStatus.COVERED
        )

    result = run(
        benchmark=bench,
        translator=translator,
        analyzer=analyzer,
        adapter=adapter,
        coverage_probe=probe,
        stub_accuracy=0.7,
        seed=11,
        db_path=db,
    )

    with connect(db) as conn:
        scores = get_scores(conn, result.run_id)
        assert set(scores) == {"all", "covered"}, scores
        assert scores["all"]["total_snippets"] == len(snippets)
        assert scores["covered"]["total_snippets"] == len(snippets) - len(excluded)
        # covered subset is strictly smaller
        assert scores["covered"]["total_snippets"] < scores["all"]["total_snippets"]

        # Every persisted outcome belongs to the canonical set.
        anns = list_annotations(conn, result.run_id)
        observed = {a["outcome"] for a in anns}
        assert observed <= {o.value for o in (Outcome.EXACT, Outcome.TYPE_MISS, Outcome.LOCATION_MISS)}
        # All three buckets present at stub accuracy 0.7 with UNSUPPORTED slice.
        assert "EXACT" in observed
        assert "TYPE_MISS" in observed
        assert "LOCATION_MISS" in observed  # excluded snippets force these

        # SPURIOUS lives in its own table (not collapsed into `annotations`).
        spurious = list_spurious(conn, result.run_id)
        # With the stub, spurious count should be 0 (stub never invents extras).
        assert spurious == []


def test_outcome_filter_is_queryable_by_inspector():
    """The inspector relies on outcome-based filtering. Exercise the query
    path (not just the schema) so a refactor that breaks the index surfaces."""
    bench = TypeEvalPyBenchmark()
    snippets = bench.load()
    from archway_benchmarks.engines.stubs import make_stub_pair

    translator, analyzer, adapter = make_stub_pair(snippets, accuracy=0.6, seed=3)
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "audit.db"
        result = run(
            benchmark=bench,
            translator=translator,
            analyzer=analyzer,
            adapter=adapter,
            stub_accuracy=0.6,
            seed=3,
            db_path=db,
        )
        with connect(db) as conn:
            exacts = list_annotations(conn, result.run_id, outcome=Outcome.EXACT)
            type_misses = list_annotations(conn, result.run_id, outcome=Outcome.TYPE_MISS)
            assert exacts and type_misses, "both buckets should be populated"
            assert all(a["outcome"] == "EXACT" for a in exacts)
            assert all(a["outcome"] == "TYPE_MISS" for a in type_misses)
