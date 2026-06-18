"""Adapter projection for subscript GT entries (`d['k']`, `a[i]`, `d['a']['b']`).

Pins the fix for the run-31 dicts/lists subscript TYPE_MISS lever
(ENGINE-dict-list-precision.md): the engine's container binding carries keyed
(`DictType.slots`) / positional (`ListType.slots`) per-key precision, but the
adapter's old `_value_element` projected only the *homogeneous* value/element
join, so every heterogeneous-slot read over-unioned into a TYPE_MISS (and a
deeper `d['a']['b']` read answered the wrong depth).

`_subscript_keys` parses the literal `[k][k2]...` chain off the GT name and
`_project_slots` walks it, preferring a populated engine slot at each level and
falling back to the homogeneous element when the slot is absent. The faithful
discipline: surface ONLY a type the engine genuinely computed (a populated slot,
or its homogeneous join); when the engine left the slot empty / produced a
`union`/`bottom` base, project nothing and leave the GT its honest miss.

Element shapes below mirror real engine output captured from the live analysis
server (experiments/adapter-projection/artifacts/engine_dicts_lists.json):
keyed dict slots are `[[literal_key, value_elt], ...]` (the key is JSON-native,
so int `1` and str `'1'` are distinct slot keys); list/tuple slots are a
positional `[value_elt, ...]` list.
"""
from __future__ import annotations

from archway_benchmarks.benchmarks.archway_adapter import ArchwayAnalysisResultAdapter
from archway_benchmarks.engines.archway import ArchwayAnalysisResult
from archway_benchmarks.types import Annotation, Location, Snippet

FILE = "fixtures/subscript/main.py"


def _pos(row, col):
    # Engine cols are 0-indexed; adapter matches GT (1-indexed) via col+1.
    return {"row": row, "col": col, "end_row": row, "end_col": col + 8}


def _event(row, col, element):
    return {"source_position": _pos(row, col), "element": element}


def _pytype(name):
    return {"kind": "pytype", "name": name}


def _callable(body=900):
    return {"kind": "callable", "body": body}


def _union(*members):
    return {"kind": "union", "elements": list(members)}


def _dict(value, slots=None):
    e = {"kind": "dict", "key": _pytype("str"), "value": value}
    if slots is not None:
        e["slots"] = slots
    return e


def _list(element, slots=None):
    e = {"kind": "list", "element": element}
    if slots is not None:
        e["slots"] = slots
    return e


def _build_result() -> ArchwayAnalysisResult:
    """Synthetic engine output; one module binding per subscript scenario."""
    module_bindings = {
        # Heterogeneous keyed dict: homogeneous value over-unions int|str, but
        # the per-key slots are precise. (row 10)
        "h": [_event(10, 0, _dict(_union(_pytype("int"), _pytype("str")),
                                  slots=[["a", _pytype("int")], ["b", _pytype("str")]]))],
        # Mixed int + str keys coexisting in one dict (row 11).
        "m": [_event(11, 0, _dict(_union(_callable(), _pytype("int")),
                                  slots=[[1, _callable()], [2, _pytype("int")], ["a", _callable()]]))],
        # Positional list slots (row 12).
        "ls": [_event(12, 0, _list(_union(_pytype("int"), _pytype("float")),
                                   slots=[_pytype("int"), _pytype("float"), _pytype("int")]))],
        # Nested dict-of-dict for a two-level chain (row 13).
        "n": [_event(13, 0, _dict(_dict(_callable()),
                                  slots=[["a", _dict(_callable(), slots=[["b", _callable()]])]]))],
        # List-of-dicts for `data[0]['name']` (row 14).
        "data": [_event(14, 0, _list(_dict(_pytype("str")),
                                     slots=[_dict(_pytype("str"), slots=[["name", _pytype("str")]])]))],
        # Dict WITHOUT slots (e.g. a `|`-merge / zip): homogeneous value only —
        # an ENGINE gap the adapter must NOT paper over (row 15).
        "g": [_event(15, 0, _dict(_union(_pytype("int"), _pytype("float"))))],
        # Union base (param_key ambiguity): not a projectable container (row 16).
        "u": [_event(16, 0, _union(_list(_pytype("int")), _dict(_pytype("float"))))],
    }
    return ArchwayAnalysisResult(
        snippet_path="fixtures/subscript",
        module_bindings=module_bindings,
        functions=(),
        module_name="main",
    )


def _snippet(annotations) -> Snippet:
    return Snippet(
        benchmark="typeevalpy",
        suite_path="fixtures/subscript",
        file_path=FILE,
        source="",
        annotations=tuple(annotations),
    )


def _gt(name, line, col, types):
    return Annotation(
        location=Location(file=FILE, line=line, col=col, kind="variable", name=name, function=None),
        types=frozenset(types),
    )


def _predict(gt_annotations):
    result = _build_result()
    out = ArchwayAnalysisResultAdapter().to_annotations(result, _snippet(gt_annotations))
    return {a.location.name: a.types for a in out}


# ----- keyed dict slot precision (the dominant lever) -----

def test_keyed_dict_slot_beats_homogeneous_union():
    # `h['a']` wants int, `h['b']` wants str. Homogeneous value is int|str, so a
    # bare projection TYPE_MISSes both. The slots are precise.
    preds = _predict([_gt("h['a']", 10, 1, {"int"}), _gt("h['b']", 10, 1, {"str"})])
    assert preds == {"h['a']": frozenset({"int"}), "h['b']": frozenset({"str"})}


def test_int_and_str_keys_are_distinct_slots():
    # `m[1]` (int 1) and `m['a']` (str 'a') must hit different slots; the type of
    # the literal disambiguates against the JSON-native slot key.
    preds = _predict([
        _gt("m['a']", 11, 1, {"callable"}),
        _gt("m[1]", 11, 1, {"callable"}),
        _gt("m[2]", 11, 1, {"int"}),
    ])
    assert preds == {
        "m['a']": frozenset({"callable"}),
        "m[1]": frozenset({"callable"}),
        "m[2]": frozenset({"int"}),
    }


def test_str_key_does_not_match_int_slot():
    # `m['1']` is the STRING '1' — no such slot (slots are int 1/2 + str 'a'),
    # so it falls back to the homogeneous value (callable|int), a faithful miss.
    preds = _predict([_gt("m['1']", 11, 1, {"callable"})])
    assert preds == {"m['1']": frozenset({"callable", "int"})}


# ----- positional list/tuple slots -----

def test_positional_list_slots():
    preds = _predict([
        _gt("ls[0]", 12, 1, {"int"}),
        _gt("ls[1]", 12, 1, {"float"}),
        _gt("ls[2]", 12, 1, {"int"}),
    ])
    assert preds == {
        "ls[0]": frozenset({"int"}),
        "ls[1]": frozenset({"float"}),
        "ls[2]": frozenset({"int"}),
    }


def test_negative_index_wraps_into_slots():
    # `ls[-1]` is the last positional slot (int), not the homogeneous join.
    preds = _predict([_gt("ls[-1]", 12, 1, {"int"})])
    assert preds == {"ls[-1]": frozenset({"int"})}


def test_out_of_range_index_falls_back_to_homogeneous():
    # `ls[9]` has no slot -> homogeneous element (int|float). Faithful miss, not
    # an invented type.
    preds = _predict([_gt("ls[9]", 12, 1, {"int"})])
    assert preds == {"ls[9]": frozenset({"float", "int"})}


# ----- multi-level chains -----

def test_nested_dict_chain_resolves_deep_slot():
    # `n['a']` is the inner dict; `n['a']['b']` walks both levels to callable.
    preds = _predict([
        _gt("n['a']", 13, 1, {"dict"}),
        _gt("n['a']['b']", 13, 1, {"callable"}),
    ])
    assert preds == {"n['a']": frozenset({"dict"}), "n['a']['b']": frozenset({"callable"})}


def test_list_of_dicts_index_then_key():
    # `data[0]` is a dict; `data[0]['name']` -> str.
    preds = _predict([
        _gt("data[0]", 14, 1, {"dict"}),
        _gt("data[0]['name']", 14, 1, {"str"}),
    ])
    assert preds == {"data[0]": frozenset({"dict"}), "data[0]['name']": frozenset({"str"})}


# ----- legitimacy guard: engine gaps stay honest misses, never papered over -----

def test_dict_without_slots_keeps_homogeneous_value():
    # `g['a']`: the engine carried no keyed slots (|-merge/zip), only the
    # homogeneous value int|float. The adapter surfaces THAT (the engine's honest
    # join) -> stays a TYPE_MISS against a single-typed GT, an engine gap routed
    # back, NOT a fabricated per-key answer.
    preds = _predict([_gt("g['a']", 15, 1, {"int"})])
    assert preds == {"g['a']": frozenset({"float", "int"})}


def test_union_base_projects_nothing():
    # `u[0]`: the base is a union of containers (engine ambiguity) — not a
    # single projectable container. The adapter emits NOTHING (LOCATION_MISS),
    # rather than inventing an element type the engine never committed to.
    preds = _predict([_gt("u[0]", 16, 1, {"int"})])
    assert preds == {}


def test_nested_chain_through_union_projects_nothing():
    # A deeper read whose intermediate is a union is unreachable: project
    # nothing instead of answering the wrong depth (the old one-level bug).
    preds = _predict([_gt("u[0]['x']", 16, 1, {"int"})])
    assert preds == {}


def test_wrong_position_not_surfaced():
    # Position is identity: a subscript GT at a line with no binding stays a miss.
    preds = _predict([_gt("h['a']", 99, 1, {"int"})])
    assert preds == {}
