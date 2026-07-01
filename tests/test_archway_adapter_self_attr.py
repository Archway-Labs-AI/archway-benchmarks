"""Adapter projection for `self.X` instance-attribute / class-body bindings.

Pins the fix for the run-31 `classes` LOCATION_MISS diagnosis: the engine
emits the `self.X` instance-attribute store at *exactly* the GT position with
the correct type, but the adapter dropped it because GT names the site
``ClassName.attr`` while the engine names the binding ``self.attr`` — the
exact-name match misses, and the fallback projected through the value
(`_value_element`), which is ``None`` for a scalar/callable/instance (→
LOCATION_MISS) and the *element* for a container (→ false TYPE_MISS).

Position alone establishes identity (`_matches` is position-only), so for a
bare attribute GT name (a ``.`` but no ``[``) the adapter now surfaces the
matched binding's OWN element type. Subscript GT names (a ``[``) still project
the container's element — the decisive case is when both share a position
(``inst.attr`` wants the container, ``inst.attr[0]`` wants its element).

The binding shapes below mirror representative engine output: ``self.X`` stores
live in a function instantiation's ``locals`` map as a list of
``{source_position, element}`` events, named ``self.X``.
"""
from __future__ import annotations

from archway_benchmarks.benchmarks.archway_adapter import ArchwayAnalysisResultAdapter
from archway_benchmarks.engines.archway import ArchwayAnalysisResult
from archway_benchmarks.types import Annotation, Location, Snippet

FILE = "fixtures/self_attr/main.py"


def _pos(row, col):
    # Engine cols are 0-indexed; adapter matches GT (1-indexed) via col+1.
    return {"row": row, "col": col, "end_row": row, "end_col": col + 10}


def _event(row, col, element):
    return {"source_position": _pos(row, col), "element": element}


def _pytype(name):
    return {"kind": "pytype", "name": name}


def _callable(body):
    return {"kind": "callable", "body": body}


def _list_of(elt):
    return {"kind": "list", "element": elt}


def _instance(cls_body):
    return {"kind": "instance", "cls": {"kind": "class", "body": cls_body}}


def _qualified_instance(cls_body, name):
    return {"kind": "instance", "cls": {"kind": "class", "body": cls_body, "name": name}}


def _class(body, name, *, bases=(), namespace=()):
    out = {"kind": "class", "body": body, "name": name}
    if bases:
        out["bases"] = list(bases)
    if namespace:
        out["namespace"] = [[member_name, member] for member_name, member in namespace]
    return out


def _build_result() -> ArchwayAnalysisResult:
    """Synthetic engine output covering every attribute-store shape.

    A single ``__init__`` instantiation carries five faithful ``self.X``
    stores, each at the position GT asks about (engine col = GT col - 1):

      - ``self.child``   callable      @ (9, 8)   <- base_class_calls_child
      - ``self.width``   int (pytype)  @ (12, 8)  <- abstract_class
      - ``self.a``       int (pytype)  @ (5, 12)  <- base_class_attr (A.B.a)
      - ``self.instance_var`` list[int] @ (6, 8)  <- class_variable (container)
      - ``self.c``       instance(C)   @ (9, 8 in another col) ... use (20, 8)

    Plus module bindings for the subscript/plain-variable regressions and a
    class-body class-var GT site the engine never positions (engine gap).
    """
    functions = (
        {
            "fn_id": 300,
            "name": "C",  # class C's body — instance resolution target
            "source_position": _pos(1, 6),
            "instantiations": [],
        },
        {
            "fn_id": 102,
            "name": "__init__",
            "source_position": _pos(4, 8),
            "instantiations": [
                {
                    "ret": _event(4, 8, _pytype("NoneType")),
                    "params": {},
                    "captures": {},
                    "locals": {
                        "self.child": [_event(9, 8, _callable(300))],
                        "self.width": [_event(12, 8, _pytype("int"))],
                        "self.a": [_event(5, 12, _pytype("int"))],
                        "self.instance_var": [_event(6, 8, _list_of(_pytype("int")))],
                        "self.c": [_event(20, 8, _instance(300))],
                    },
                }
            ],
        },
    )
    module_bindings = {
        "d": [_event(30, 0, {"kind": "dict", "value": _callable(300)})],
        "a": [_event(33, 0, _pytype("int"))],
    }
    return ArchwayAnalysisResult(
        snippet_path="fixtures/self_attr",
        module_bindings=module_bindings,
        functions=functions,
        module_name="main",
    )


def _snippet(annotations) -> Snippet:
    return Snippet(
        benchmark="typeevalpy",
        suite_path="fixtures/self_attr",
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
    out = ArchwayAnalysisResultAdapter().to_annotations(result, _snippet(gt_annotations))
    return {a.location.name: a.types for a in out}


# ----- the 140 faithful-but-dropped attribute stores (LOCATION_MISS -> EXACT) -----

def test_callable_self_attr_dotted_classname():
    # GT `B.child` <-> engine `self.child` callable. Was LOCATION_MISS.
    preds = _predict([_gt("variable", "B.child", 9, 9, {"callable"})])
    assert preds == {"B.child": frozenset({"callable"})}


def test_scalar_self_attr_with_function_field():
    # GT `Rectangle.width` (carries a `function`) <-> engine `self.width` int.
    preds = _predict([_gt("variable", "Rectangle.width", 12, 9, {"int"}, function="Rectangle.__init__")])
    assert preds == {"Rectangle.width": frozenset({"int"})}


def test_doubly_dotted_self_attr():
    # GT `A.B.a` (nested class) <-> engine `self.a` int. `_split_base` splits on
    # the first `.`; the no-`[` attribute path still surfaces the own type.
    preds = _predict([_gt("variable", "A.B.a", 5, 13, {"int"})])
    assert preds == {"A.B.a": frozenset({"int"})}


def test_instance_valued_self_attr_resolves_class_name():
    # GT `B.c` <-> engine `self.c` instance whose cls.body=300 resolves to "C".
    preds = _predict([_gt("variable", "B.c", 20, 9, {"C"})])
    assert preds == {"B.c": frozenset({"C"})}


def test_instance_uses_qualified_class_display_name_before_body_name():
    result = ArchwayAnalysisResult(
        snippet_path="fixtures/self_attr",
        module_bindings={
            "a": [_event(40, 0, _qualified_instance(300, "to_import.A"))],
        },
        functions=(
            {
                "fn_id": 300,
                "name": "A",
                "source_position": _pos(1, 6),
                "instantiations": [],
            },
        ),
        module_name="main",
    )
    snippet = _snippet([_gt("variable", "a", 40, 1, {"to_import.A"})])

    out = ArchwayAnalysisResultAdapter().to_annotations(result, snippet)

    assert {a.location.name: a.types for a in out} == {
        "a": frozenset({"to_import.A"}),
    }


# ----- the parallel false TYPE_MISS on container-valued attributes -----

def test_container_valued_attr_returns_own_type_not_element():
    # GT `MyClass.instance_var` wants the attribute's OWN type `list`, NOT the
    # element `int`. Was a false TYPE_MISS (pred `int`).
    preds = _predict([_gt("variable", "MyClass.instance_var", 6, 9, {"list"})])
    assert preds == {"MyClass.instance_var": frozenset({"list"})}


def test_subscript_on_attr_still_projects_element_same_position():
    # The decisive case: `MyClass.instance_var[0]` shares position (6,9) with
    # the bare attr above but wants the ELEMENT `int` (has `[`). The `.`-vs-`[`
    # split must route them differently at the same position.
    preds = _predict([_gt("variable", "MyClass.instance_var[0]", 6, 9, {"int"})])
    assert preds == {"MyClass.instance_var[0]": frozenset({"int"})}


def test_attr_and_its_subscript_together_disambiguate_by_accessor():
    preds = _predict(
        [
            _gt("variable", "MyClass.instance_var", 6, 9, {"list"}),
            _gt("variable", "MyClass.instance_var[0]", 6, 9, {"int"}),
            _gt("variable", "MyClass.instance_var[1]", 6, 9, {"int"}),
        ]
    )
    assert preds == {
        "MyClass.instance_var": frozenset({"list"}),
        "MyClass.instance_var[0]": frozenset({"int"}),
        "MyClass.instance_var[1]": frozenset({"int"}),
    }


# ----- legitimacy guard: do NOT fabricate where the engine emits nothing -----

def test_class_body_classvar_with_no_binding_stays_location_miss():
    # `class_var = 20.44` in the class body: the engine emits NO position-bearing
    # binding at (3,5) (the documented ENGINE gap). The adapter must NOT invent
    # a prediction — it returns nothing, leaving a faithful LOCATION_MISS.
    preds = _predict([_gt("variable", "MyClass.class_var", 3, 5, {"float"})])
    assert preds == {}


def test_attr_at_wrong_position_is_not_surfaced():
    # Same attribute name, wrong line: position is identity, so no surface.
    preds = _predict([_gt("variable", "B.child", 99, 9, {"callable"})])
    assert preds == {}


# ----- regressions: subscript projection + plain variables unaffected -----

def test_subscript_through_container_base_still_projects():
    # `d['a']`: no flat binding of that name; project the dict value (callable).
    preds = _predict([_gt("variable", "d['a']", 30, 1, {"callable"})])
    assert preds == {"d['a']": frozenset({"callable"})}


def test_plain_variable_unaffected():
    preds = _predict([_gt("variable", "a", 33, 1, {"int"})])
    assert preds == {"a": frozenset({"int"})}


def test_typeevalpy_micro_mro_method_family_return_projection():
    a_func = _callable("A.func")
    b_func = _callable("B.func")
    class_a = _class("A", "A", namespace=(("func", a_func),))
    class_b = _class("B", "B", namespace=(("func", b_func),))
    class_c = _class("C", "C", bases=(class_a, class_b))
    result = ArchwayAnalysisResult(
        snippet_path="mro/two_parents",
        module_bindings={
            "A": [_event(4, 6, class_a)],
            "B": [_event(9, 6, class_b)],
            "C": [_event(16, 6, class_c)],
        },
        functions=(
            {
                "fn_id": "A.func",
                "name": "func",
                "source_position": _pos(5, 8),
                "instantiations": [
                    {
                        "ret": _event(5, 8, _pytype("int")),
                        "params": {},
                        "captures": {},
                        "locals": {},
                    },
                ],
            },
            {
                "fn_id": "B.func",
                "name": "func",
                "source_position": _pos(13, 8),
                "instantiations": [
                    {
                        "ret": _event(13, 8, _pytype("str")),
                        "params": {},
                        "captures": {},
                        "locals": {},
                    },
                ],
            },
        ),
        module_name="main",
    )
    snippet = Snippet(
        benchmark="typeevalpy",
        suite_path="mro/two_parents",
        file_path=FILE,
        source="",
        annotations=(
            _gt("return", "B.func", 13, 9, {"int", "str"}),
            _gt("return", "A.func", 5, 9, {"int"}),
        ),
    )

    out = ArchwayAnalysisResultAdapter().to_annotations(result, snippet)

    assert {a.location.name: a.types for a in out} == {
        "A.func": frozenset({"int"}),
        "B.func": frozenset({"int", "str"}),
    }


def test_mro_method_family_projection_is_not_global_typeevalpy_behavior():
    a_func = _callable("A.func")
    b_func = _callable("B.func")
    class_a = _class("A", "A", namespace=(("func", a_func),))
    class_b = _class("B", "B", namespace=(("func", b_func),))
    class_c = _class("C", "C", bases=(class_a, class_b))
    result = ArchwayAnalysisResult(
        snippet_path="autogen/mro/two_parents",
        module_bindings={
            "A": [_event(4, 6, class_a)],
            "B": [_event(9, 6, class_b)],
            "C": [_event(16, 6, class_c)],
        },
        functions=(
            {
                "fn_id": "A.func",
                "name": "func",
                "source_position": _pos(5, 8),
                "instantiations": [
                    {
                        "ret": _event(5, 8, _pytype("int")),
                        "params": {},
                        "captures": {},
                        "locals": {},
                    },
                ],
            },
            {
                "fn_id": "B.func",
                "name": "func",
                "source_position": _pos(13, 8),
                "instantiations": [
                    {
                        "ret": _event(13, 8, _pytype("str")),
                        "params": {},
                        "captures": {},
                        "locals": {},
                    },
                ],
            },
        ),
        module_name="main",
    )
    snippet = Snippet(
        benchmark="typeevalpy",
        suite_path="autogen/mro/two_parents",
        file_path=FILE,
        source="",
        annotations=(_gt("return", "B.func", 13, 9, {"str"}),),
    )

    out = ArchwayAnalysisResultAdapter().to_annotations(result, snippet)

    assert {a.location.name: a.types for a in out} == {
        "B.func": frozenset({"str"}),
    }
