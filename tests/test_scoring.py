"""Three-bucket scoring tests.

Validates EXACT / TYPE_MISS / LOCATION_MISS / SPURIOUS classification and
the leaderboard-shaped reproduction at stub@1.0 and stub@0.0.
"""
from archway_benchmarks.benchmarks import TypeEvalPyBenchmark
from archway_benchmarks.engines.stubs import StubTranslation, make_stub_pair
from archway_benchmarks.outcome import Outcome
from archway_benchmarks.scoring import score_snippet, score_predictions
from archway_benchmarks.benchmarks.typeevalpy import _location_to_record
from archway_benchmarks.types import Location


def _loc(line, col, kind, name, function=None, file="m.py"):
    return Location(file=file, line=line, col=col, kind=kind, name=name, function=function)


def test_exact_match_classified_as_exact():
    gt = {_loc(2, 5, "return", "f"): frozenset({"int"})}
    pred = {_loc(2, 5, "return", "f"): frozenset({"int"})}
    s = score_snippet("dummy", gt, pred, _location_to_record)
    assert [o.outcome for o in s.outcomes] == [Outcome.EXACT]
    assert s.is_sound and s.is_complete
    assert not s.spurious_predictions


def test_wrong_type_classified_as_type_miss():
    gt = {_loc(2, 5, "return", "f"): frozenset({"int"})}
    pred = {_loc(2, 5, "return", "f"): frozenset({"str"})}
    s = score_snippet("dummy", gt, pred, _location_to_record)
    assert [o.outcome for o in s.outcomes] == [Outcome.TYPE_MISS]
    assert not s.is_sound and not s.is_complete


def test_no_prediction_classified_as_location_miss():
    gt = {_loc(2, 5, "return", "f"): frozenset({"int"})}
    s = score_snippet("dummy", gt, {}, _location_to_record)
    assert [o.outcome for o in s.outcomes] == [Outcome.LOCATION_MISS]
    assert not s.is_sound and s.is_complete  # nothing predicted -> trivially no FP


def test_unmatched_prediction_classified_as_spurious():
    gt = {_loc(2, 5, "return", "f"): frozenset({"int"})}
    pred = {
        _loc(2, 5, "return", "f"): frozenset({"int"}),
        _loc(99, 0, "variable", "ghost"): frozenset({"int"}),
    }
    s = score_snippet("dummy", gt, pred, _location_to_record)
    assert [o.outcome for o in s.outcomes] == [Outcome.EXACT]
    assert len(s.spurious_predictions) == 1
    assert not s.is_complete  # SPURIOUS hurts complete
    assert s.is_sound  # all GT was still caught


def test_type_normalization_callable_is_lenient():
    # Vendor format_type strips bracketed content: Callable[[str],str] -> callable
    gt = {_loc(2, 5, "return", "f"): frozenset({"callable"})}
    pred = {_loc(2, 5, "return", "f"): frozenset({"Callable[[str], str]"})}
    s = score_snippet("dummy", gt, pred, _location_to_record)
    assert s.outcomes[0].outcome == Outcome.EXACT


def test_full_corpus_stub_at_1_is_perfect():
    bench = TypeEvalPyBenchmark()
    snippets = bench.load()
    _, analyze, adapter = make_stub_pair(snippets, accuracy=1.0, seed=42)

    predictions = {}
    for snip in snippets:
        result = analyze.analyze(StubTranslation(path=snip.file_path, source=snip.source))
        for ann in adapter.to_annotations(result, snip):
            predictions[ann.location] = ann.types

    scores = score_predictions(bench, predictions)
    assert scores.total_annotations == 850
    assert scores.exact_total == 850
    assert scores.files_sound == 153
    assert scores.files_complete == 153
    assert scores.annotation_precision == 1.0
    assert scores.annotation_recall == 1.0


def test_full_corpus_stub_at_067_is_leaderboard_shaped():
    bench = TypeEvalPyBenchmark()
    snippets = bench.load()
    _, analyze, adapter = make_stub_pair(snippets, accuracy=0.67, seed=12345)

    predictions = {}
    for snip in snippets:
        result = analyze.analyze(StubTranslation(path=snip.file_path, source=snip.source))
        for ann in adapter.to_annotations(result, snip):
            predictions[ann.location] = ann.types

    scores = score_predictions(bench, predictions)
    # HeaderGen tops the leaderboard at 532/850 ≈ 62.6%. Stub@0.67 should
    # land in the 0.55–0.78 band — generous to absorb the randomness.
    exact_rate = scores.exact_total / scores.total_annotations
    assert 0.55 <= exact_rate <= 0.78, exact_rate
    assert 0 < scores.files_sound < 153
