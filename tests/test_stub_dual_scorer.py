"""The stub must score correctly under BOTH the strict and lenient scorers.

The stub already inherits GT's `col_offset`, so a perfect (accuracy=1.0)
stub should reproduce the full GT under each predicate. If we ever break
the col_offset convention or the lenient/strict scorer wiring, this is
the canary.
"""
from __future__ import annotations

from archway_benchmarks.benchmarks import TypeEvalPyBenchmark
from archway_benchmarks.engines.stubs import StubTranslation, make_stub_pair
from archway_benchmarks.scoring import score_predictions
from archway_benchmarks.scoring.typeevalpy_lenient import score_predictions_lenient


def _stub_predictions(accuracy: float, seed: int) -> tuple[TypeEvalPyBenchmark, dict]:
    bench = TypeEvalPyBenchmark()
    snippets = bench.load()
    _t, analyze, adapter = make_stub_pair(snippets, accuracy=accuracy, seed=seed)
    predictions: dict = {}
    for snip in snippets:
        result = analyze.analyze(StubTranslation(path=snip.file_path, source=snip.source))
        for ann in adapter.to_annotations(result, snip):
            predictions[ann.location] = ann.types
    return bench, predictions


def test_stub_at_1_is_perfect_under_strict():
    bench, predictions = _stub_predictions(accuracy=1.0, seed=42)
    s = score_predictions(bench, predictions)
    assert s.exact_total == s.total_annotations == 850
    assert s.files_sound == s.total_snippets == 153


def test_stub_at_1_is_perfect_under_lenient():
    bench, predictions = _stub_predictions(accuracy=1.0, seed=42)
    s = score_predictions_lenient(bench, predictions)
    assert s.exact_total == s.total_annotations == 850, (
        "lenient should also be perfect — the stub emits convention-correct "
        "1-indexed col_offset inherited from GT; a regression here means "
        "either the stub broke or the lenient scorer was rewired wrong"
    )
    assert s.files_sound == s.total_snippets == 153


def test_strict_and_lenient_agree_on_stub_at_1():
    """Under accuracy=1.0 both scorers should land on the SAME number."""
    bench, predictions = _stub_predictions(accuracy=1.0, seed=42)
    strict = score_predictions(bench, predictions)
    lenient = score_predictions_lenient(bench, predictions)
    assert strict.exact_total == lenient.exact_total
    assert strict.exact_by_kind == lenient.exact_by_kind
