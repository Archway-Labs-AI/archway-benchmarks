from archway_benchmarks.engines.stubs import (
    StubTranslation,
    StubTranslationEngine,
    make_stub_pair,
)
from archway_benchmarks.types import Annotation, Location, Snippet


def _snippet(path: str, annotations: list[Annotation]) -> Snippet:
    return Snippet(
        benchmark="test",
        suite_path="dummy",
        file_path=path,
        source="",
        annotations=tuple(annotations),
    )


def _annotation(name: str, type_str: str) -> Annotation:
    loc = Location(file="m.py", line=1, col=0, kind="variable", name=name)
    return Annotation(location=loc, types=frozenset({type_str}))


def test_translation_engine_returns_placeholder():
    eng = StubTranslationEngine()
    t = eng.translate("x = 1", "m.py")
    assert isinstance(t, StubTranslation)
    assert t.path == "m.py"


def test_stub_accuracy_1_reproduces_ground_truth():
    snip = _snippet("m.py", [_annotation("x", "int"), _annotation("y", "str")])
    _, analyze, adapter = make_stub_pair([snip], accuracy=1.0, seed=42)
    result = analyze.analyze(StubTranslation(path="m.py", source=""))
    annotations = adapter.to_annotations(result, snip)
    pred = {a.location: a.types for a in annotations}
    assert pred == {a.location: a.types for a in snip.annotations}


def test_stub_accuracy_0_never_returns_ground_truth():
    snip = _snippet("m.py", [_annotation("x", "int")])
    _, analyze, adapter = make_stub_pair([snip], accuracy=0.0, seed=0)
    result = analyze.analyze(StubTranslation(path="m.py", source=""))
    annotations = adapter.to_annotations(result, snip)
    assert annotations[0].types != frozenset({"int"})


def test_stub_accuracy_rate_is_within_tolerance():
    # 1000 annotations all expecting "int"; at p=0.6 we expect ~600 correct.
    anns = [_annotation(f"v{i}", "int") for i in range(1000)]
    snip = _snippet("m.py", anns)
    _, analyze, adapter = make_stub_pair([snip], accuracy=0.6, seed=7)
    result = analyze.analyze(StubTranslation(path="m.py", source=""))
    out = adapter.to_annotations(result, snip)
    correct = sum(1 for a in out if a.types == frozenset({"int"}))
    assert 540 <= correct <= 660, correct


def test_invalid_accuracy_rejected():
    import pytest

    with pytest.raises(ValueError):
        make_stub_pair([], accuracy=1.5)


def test_stub_only_accepts_stub_translation():
    import pytest

    _, analyze, _ = make_stub_pair([], accuracy=0.5)
    with pytest.raises(TypeError):
        analyze.analyze(object())
