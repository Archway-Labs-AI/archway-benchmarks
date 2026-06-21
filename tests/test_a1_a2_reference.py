"""A1+A2 reference fixture: the clean known-good target.

Predicts every A1 (int/str) + A2 (callable) GT annotation correctly and
leaves A3–A5 unpredicted. Drives the real adapter → real scorer (NOT the
noise stub) so the pinned numbers reflect end-to-end harness behaviour.

## How this reference is used

Compare a scalar/callable reference run against these numbers:
  - **below the fixture**  -> the gap is the corresponding inference logic.
  - **at/above the fixture** -> the harness + coordinate plumbing are sound.

## Pinned actuals

  micro   : 660 / 850 EXACT (77.6%)  · FR=197 FP=88 LV=375  (GT commit ea13026d)
  autogen : 49,176 / 77,223 EXACT (63.7%)  · return=5,399 parameter=635 variable=43,142
            (GT commit 9afcfc9b — autogen position re-derivation, run-31 corpus)

Strict and lenient scorers produce identical numbers because the fixture
inherits GT's 1-indexed col_offset — confirming the col_offset convention
documented in `archway_benchmarks/typeevalpy_mapping.py`.
"""
from __future__ import annotations

import pytest

from archway_benchmarks.benchmarks import (
    TypeEvalPyAutogenBenchmark,
    TypeEvalPyBenchmark,
)
from archway_benchmarks.benchmarks.typeevalpy import (
    _DEFAULT_AUTOGEN_CORPUS,
    _location_to_record,
)
from archway_benchmarks.scoring import score_predictions
from archway_benchmarks.scoring.typeevalpy_lenient import score_predictions_lenient
from tests.fixtures.archway_fixture import (
    ArchwayAnalysisResultAdapter,
    FixtureAnalysisEngine,
    FixtureTranslationEngine,
    build_a1_a2_reference_fixture,
)

requires_autogen = pytest.mark.skipif(
    not _DEFAULT_AUTOGEN_CORPUS.exists(),
    reason="TypeEvalPy Autogen corpus is generated and not present",
)


def _drive_fixture(benchmark) -> dict:
    """Build the A1+A2 reference output and project it through the real
    adapter, then return predictions as a Location -> types dict."""
    snippets = benchmark.load()
    fixtures_by_path = {
        snip.file_path: build_a1_a2_reference_fixture(snip) for snip in snippets
    }
    translator = FixtureTranslationEngine()
    analyzer = FixtureAnalysisEngine(fixtures_by_path)
    adapter = ArchwayAnalysisResultAdapter()

    predictions: dict = {}
    for snip in snippets:
        translation = translator.translate(snip.source, snip.file_path)
        result = analyzer.analyze(translation)
        for ann in adapter.to_annotations(result, snip):
            predictions[ann.location] = ann.types
    return predictions


# ----- Pinned numbers (modify only when GT changes and the test is verified) ----

def test_a1_a2_reference_micro_strict():
    bench = TypeEvalPyBenchmark()
    s = score_predictions(bench, _drive_fixture(bench))
    assert s.exact_total == 660, (s.exact_total, "expected 660/850 EXACT on micro")
    assert s.total_annotations == 850
    # Strict scorer requires col_offset match; identical to lenient because
    # the fixture inherits GT coordinates.
    assert s.exact_by_kind == {"return": 197, "parameter": 88, "variable": 375}


def test_a1_a2_reference_micro_lenient():
    bench = TypeEvalPyBenchmark()
    s = score_predictions_lenient(bench, _drive_fixture(bench))
    assert s.exact_total == 660
    assert s.exact_by_kind == {"return": 197, "parameter": 88, "variable": 375}


@requires_autogen
def test_a1_a2_reference_autogen_strict():
    bench = TypeEvalPyAutogenBenchmark()
    s = score_predictions(bench, _drive_fixture(bench))
    assert s.exact_total == 49176, s.exact_total
    assert s.total_annotations == 77223
    assert s.exact_by_kind == {"return": 5399, "parameter": 635, "variable": 43142}


@requires_autogen
def test_a1_a2_reference_autogen_lenient():
    bench = TypeEvalPyAutogenBenchmark()
    s = score_predictions_lenient(bench, _drive_fixture(bench))
    assert s.exact_total == 49176
    assert s.exact_by_kind == {"return": 5399, "parameter": 635, "variable": 43142}


def test_a1_a2_reference_only_predicts_buckets_a1_and_a2():
    """Sanity: every prediction's GT type is A1 (int/str) or A2 (callable).
    If a future change leaks A3/A4/A5 into the reference, this catches it."""
    from archway_benchmarks.rule_buckets import classify

    bench = TypeEvalPyBenchmark()
    snippets = bench.load()
    gt_lookup = {ann.location: ann.types for snip in snippets for ann in snip.annotations}
    for loc in _drive_fixture(bench):
        bucket = classify(gt_lookup.get(loc, frozenset()))
        assert bucket in ("A1", "A2"), (loc, bucket)
