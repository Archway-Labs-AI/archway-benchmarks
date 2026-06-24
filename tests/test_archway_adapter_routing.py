"""Regression tests for the REAL Archway adapter's name-routing.

The functor-seam test exercises the *fixture* adapter (a simpler contract).
This module drives the production adapter
(`archway_benchmarks.benchmarks.archway_adapter.ArchwayAnalysisResultAdapter`)
directly against synthetic engine payloads in the `FinalizedAnalysis` shape
(`module_bindings` + `functions`).

It pins the fix for the `_split_base` misrouting bug: dotted GT names —
method / nested-function returns (`Class.method`) and instance-attribute
reads (`self.smth`) — were being routed into the subscript/attribute value-
projection branch and dropped (LOCATION_MISS), even though the engine
computes the right type at the right source position. Returns must resolve
via the callable's instantiation `ret`, and a flat `self.smth` binding must
be flattened directly — while genuine subscripts (`d['a']`) still project.
"""
from __future__ import annotations

from archway_benchmarks.benchmarks.archway_adapter import ArchwayAnalysisResultAdapter
from archway_benchmarks.engines.archway import ArchwayAnalysisResult
from archway_benchmarks.types import Annotation, Location, Snippet

FILE = "fixtures/routing/main.py"


def _pos(row, col):
    # Engine cols are 0-indexed; the adapter matches GT (1-indexed) via col+1.
    return {"row": row, "col": col, "end_row": row, "end_col": col + 1}


def _event(row, col, element):
    return {"source_position": _pos(row, col), "element": element}


def _pytype(name):
    return {"kind": "pytype", "name": name}


def _callable(body):
    return {"kind": "callable", "body": body}


def _build_result() -> ArchwayAnalysisResult:
    """Synthetic engine output covering all four routing shapes.

    - `func1` (fn_id 100): a method whose def-identifier sits at engine
      (row 8, col 8) and whose single instantiation returns `str`.
    - `A.__init__` (fn_id 102): one instantiation whose locals carry a flat
      `self.smth` binding at (row 6, col 8) holding a callable value.
    - module binding `d`: a dict at (row 12, col 0) whose value is callable.
    - module binding `a`: a plain int at (row 15, col 0).
    """
    functions = (
        {
            "fn_id": 100,
            "name": "func1",
            "source_position": _pos(8, 8),
            "instantiations": [
                {
                    "ret": _event(9, 15, _pytype("str")),
                    "params": {},
                    "captures": {},
                    "locals": {},
                }
            ],
        },
        {
            "fn_id": 102,
            "name": "__init__",
            "source_position": _pos(5, 8),
            "instantiations": [
                {
                    "ret": _event(5, 8, _pytype("NoneType")),
                    "params": {},
                    "captures": {},
                    "locals": {"self.smth": [_event(6, 8, _callable(100))]},
                }
            ],
        },
    )
    module_bindings = {
        "d": [_event(12, 0, {"kind": "dict", "value": _callable(100)})],
        "a": [_event(15, 0, _pytype("int"))],
    }
    return ArchwayAnalysisResult(
        snippet_path="fixtures/routing",
        module_bindings=module_bindings,
        functions=functions,
        module_name="main",
    )


def _snippet(annotations) -> Snippet:
    return Snippet(
        benchmark="typeevalpy",
        suite_path="fixtures/routing",
        file_path=FILE,
        source="",
        annotations=tuple(annotations),
    )


def _gt(kind, name, line, col, types, function=None):
    return Annotation(
        location=Location(file=FILE, line=line, col=col, kind=kind, name=name, function=function),
        types=frozenset(types),
    )


def _predict(gt_annotations):
    result = _build_result()
    snippet = _snippet(gt_annotations)
    out = ArchwayAnalysisResultAdapter().to_annotations(result, snippet)
    return {a.location.name: a.types for a in out}


def test_dotted_method_return_resolves():
    # `MyClass.func1` return at L8C9 — was LOCATION_MISS, must now be `str`.
    preds = _predict([_gt("return", "MyClass.func1", 8, 9, {"str"})])
    assert preds == {"MyClass.func1": frozenset({"str"})}


def test_dotted_method_return_resolves_string_body_ids():
    result = _build_result()
    result.functions[0]["fn_id"] = "sid:v1:body:func1"
    result.functions[1]["instantiations"][0]["locals"]["self.smth"][0]["element"] = _callable(
        "sid:v1:body:func1"
    )
    snippet = _snippet([_gt("return", "MyClass.func1", 8, 9, {"str"})])

    out = ArchwayAnalysisResultAdapter().to_annotations(result, snippet)

    assert {a.location.name: a.types for a in out} == {
        "MyClass.func1": frozenset({"str"})
    }


def test_self_attribute_read_resolves_directly():
    # Flat `self.smth` binding at L6C9 — was LOCATION_MISS, must now be callable.
    preds = _predict([_gt("variable", "self.smth", 6, 9, {"callable"}, function="A.__init__")])
    assert preds == {"self.smth": frozenset({"callable"})}


def test_subscript_still_projects_through_base():
    # `d['a']` at L12C1: no flat binding of that name — project the dict value.
    preds = _predict([_gt("variable", "d['a']", 12, 1, {"callable"})])
    assert preds == {"d['a']": frozenset({"callable"})}


def test_plain_variable_unaffected():
    preds = _predict([_gt("variable", "a", 15, 1, {"int"})])
    assert preds == {"a": frozenset({"int"})}


def test_all_routing_shapes_together():
    preds = _predict(
        [
            _gt("return", "MyClass.func1", 8, 9, {"str"}),
            _gt("variable", "self.smth", 6, 9, {"callable"}, function="A.__init__"),
            _gt("variable", "d['a']", 12, 1, {"callable"}),
            _gt("variable", "a", 15, 1, {"int"}),
        ]
    )
    assert preds == {
        "MyClass.func1": frozenset({"str"}),
        "self.smth": frozenset({"callable"}),
        "d['a']": frozenset({"callable"}),
        "a": frozenset({"int"}),
    }
