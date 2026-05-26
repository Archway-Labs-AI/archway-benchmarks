"""End-to-end Runner + Store smoke test.

Runs the stub trio over the full corpus, persists to a temp SQLite, and
verifies the store schema is queryable and the scores match the in-memory
aggregate.
"""
import pytest

from archway_benchmarks.benchmarks import TypeEvalPyBenchmark
from archway_benchmarks.coverage import CoverageStatus
from archway_benchmarks.engines.stubs import make_stub_pair
from archway_benchmarks.outcome import Outcome
from archway_benchmarks.runner import run
from archway_benchmarks.store import (
    connect,
    get_scores,
    list_annotations,
    list_runs,
    list_snippets,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "runs.db"


def test_stub_at_1_persists_perfect_scores(db_path):
    bench = TypeEvalPyBenchmark()
    snippets = bench.load()
    translator, analyzer, adapter = make_stub_pair(snippets, accuracy=1.0, seed=42)

    result = run(
        benchmark=bench,
        translator=translator,
        analyzer=analyzer,
        adapter=adapter,
        stub_accuracy=1.0,
        seed=42,
        db_path=db_path,
    )

    assert result.all_scores.exact_total == 850
    assert result.covered_scores.exact_total == 850
    assert result.all_scores.files_sound == 153

    with connect(db_path) as conn:
        runs = list_runs(conn)
        assert len(runs) == 1
        scores = get_scores(conn, runs[0].id)
        assert set(scores.keys()) == {"all", "covered"}
        assert scores["all"]["exact_total"] == 850
        assert scores["covered"]["exact_total"] == 850

        snippets_rows = list_snippets(conn, runs[0].id)
        assert len(snippets_rows) == 153
        assert all(r["translation_status"] == CoverageStatus.COVERED.value for r in snippets_rows)


def test_stub_at_067_has_three_buckets(db_path):
    bench = TypeEvalPyBenchmark()
    snippets = bench.load()
    translator, analyzer, adapter = make_stub_pair(snippets, accuracy=0.67, seed=12345)

    result = run(
        benchmark=bench,
        translator=translator,
        analyzer=analyzer,
        adapter=adapter,
        stub_accuracy=0.67,
        seed=12345,
        db_path=db_path,
    )

    with connect(db_path) as conn:
        exact = list_annotations(conn, result.run_id, outcome=Outcome.EXACT)
        type_miss = list_annotations(conn, result.run_id, outcome=Outcome.TYPE_MISS)
        loc_miss = list_annotations(conn, result.run_id, outcome=Outcome.LOCATION_MISS)
        # Stub always predicts at every GT location, so LOCATION_MISS = 0.
        assert len(loc_miss) == 0
        assert len(exact) + len(type_miss) == 850
        assert len(exact) > 0 and len(type_miss) > 0


def test_uncovered_snippets_excluded_from_covered_scores(db_path):
    """With a coverage_probe that marks half the snippets UNSUPPORTED,
    `covered` scores reflect only the half we attempted."""
    bench = TypeEvalPyBenchmark()
    snippets = bench.load()
    translator, analyzer, adapter = make_stub_pair(snippets, accuracy=1.0, seed=42)

    paths_sorted = sorted(s.suite_path for s in snippets)
    excluded = set(paths_sorted[: len(paths_sorted) // 2])

    def probe(snip):
        return (
            CoverageStatus.UNSUPPORTED
            if snip.suite_path in excluded
            else CoverageStatus.COVERED
        )

    result = run(
        benchmark=bench,
        translator=translator,
        analyzer=analyzer,
        adapter=adapter,
        coverage_probe=probe,
        stub_accuracy=1.0,
        seed=42,
        db_path=db_path,
    )

    # All-corpus aggregate: missing predictions for excluded -> LOCATION_MISS.
    assert result.all_scores.exact_total < 850
    # Covered-subset aggregate: only attempted snippets, all perfect (acc=1.0).
    assert result.covered_scores.exact_total == result.covered_scores.total_annotations
    assert result.covered_scores.total_snippets == len(snippets) - len(excluded)
