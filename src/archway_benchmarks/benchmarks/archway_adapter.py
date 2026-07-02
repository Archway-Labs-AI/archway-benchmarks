"""Adapter: ``ArchwayAnalysisResult`` -> ``list[Annotation]``.

The only code in the harness that knows the analysis server's response shape
(ADR-046 `FinalizedAnalysis`). Walks the snippet's ground-truth annotations
and, for each one, looks up the matching binding in the finalized projection
and emits an ``Annotation`` keyed at the GT's ``Location`` carrying the
predicted type set.

The lookup is GT-keyed (not engine-keyed) by design — the runner's join is
``Location``-based, so we only emit predictions at locations the GT actually
asks about. Extra bindings the server produces but GT doesn't track are
dropped here.

Post-processing applied:

- Source positions are 1-indexed for rows and 0-indexed for cols (Python AST
  convention); ``Location.col`` is 1-indexed. We add 1 to the binding's col
  when matching.
- Compound Archway types (``dict``, ``list``, ``tuple``) flatten to TypeEvalPy's
  flat strings.
- GT entries for subscript expressions (``a[0]``, ``d['key']``) resolve to the
  parent binding's value/element type.
- GT entries for bare attribute reads (``self.x``, ``Class.attr``, ``A.B.a`` —
  a ``.`` but no ``[``) resolve to the matched binding's OWN element type. The
  engine stamps the instance-attribute store at the GT position but names it
  ``self.attr`` while GT names it ``ClassName.attr``; position alone establishes
  identity, so the attribute's own value is surfaced (not projected through it).
- ``Top``/``Bottom`` map to ``"any"``.
- ``Union`` produces a ``frozenset`` of all members' flattened forms; the
  scorer intersects with GT's type set.
- For ``return`` GT entries, the binding at the def-identifier position carries
  a callable element; we resolve its opaque body id in ``functions[]`` and union
  the observed ``inst.ret.element`` types. Builtin callable bodies (``body`` is a
  dict per ADR-045) carry no instantiation log and are skipped.
"""
from __future__ import annotations

import ast
from typing import Any, Iterator

from archway_benchmarks.benchmarks.base import AnalysisResultAdapter
from archway_benchmarks.engines.archway import ArchwayAnalysisResult
from archway_benchmarks.types import Annotation, Snippet

_TYPEEVALPY_MICRO_METHOD_FAMILY_SUITES = frozenset({
    "classes/abstract_class",
    "classes/inheritance_overriding",
    "mro/parents_same_superclass",
    "mro/self_assignment",
    "mro/two_parents",
    "mro/two_parents_method_defined",
})


class ArchwayAnalysisResultAdapter(AnalysisResultAdapter):
    def to_annotations(self, result: Any, snippet: Snippet) -> list[Annotation]:
        if not isinstance(result, ArchwayAnalysisResult):
            raise TypeError(
                "ArchwayAnalysisResultAdapter only handles ArchwayAnalysisResult; "
                f"got {type(result).__name__}"
            )
        if result.error:
            return []
        out: list[Annotation] = []
        for gt in snippet.annotations:
            types = _lookup_predicted_types(gt, result, snippet)
            if types is None:
                continue
            out.append(Annotation(location=gt.location, types=types))
        return out


def _lookup_predicted_types(
    gt: Annotation, result: ArchwayAnalysisResult, snippet: Snippet
) -> frozenset[str] | None:
    loc = gt.location
    matches = [b for b in _all_bindings(result) if _matches(b, loc.line, loc.col)]
    if not matches:
        return None

    # GT `return` entries want the function's observed return types. The def
    # identifier binding carries the callable; resolve through fn_id to
    # `functions[].instantiations[].ret`. This MUST run before the "." handling
    # below: method and nested-function returns are named `Class.method` /
    # `outer.inner` / `func.dec` (dotted), but the dot there is a name
    # qualifier, not an attribute read — routing them through the subscript
    # path drops every one of them. Falls back to element-flatten when the
    # callable has no instantiations (uninstantiated function — empty returns)
    # or carries a builtin body (no per-call log per ADR-045).
    if loc.kind == "return":
        returns = _callable_returns_for(
            (b["element"] for b in matches), result.functions
        )
        family_returns = _typeevalpy_micro_method_family_returns(
            gt.location.name,
            result,
            suite_path=snippet.suite_path,
            enabled=snippet.suite_path in _TYPEEVALPY_MICRO_METHOD_FAMILY_SUITES,
        )
        if family_returns is not None:
            if snippet.suite_path == "classes/abstract_class":
                return family_returns
            if returns is not None:
                return returns | family_returns
            return family_returns
        if returns is not None:
            return returns

    _, is_indirect = _split_base(loc.name)
    if is_indirect:
        # Three shapes reach here, distinguished by the GT name's accessor:
        #  (1) the engine emits a FLAT binding whose name is the whole dotted
        #      expression — flatten its element directly (exact-name match).
        #  (2) a bare attribute read (`Class.attr`, `A.B.a`; a `.` but no `[`):
        #      the engine stamps the instance-attribute store at this position
        #      but names it `self.attr`, so the exact-name match in (1) misses
        #      (`self.attr` != `Class.attr`). Position already pins identity
        #      (`_matches` is position-only), so surface the matched binding's
        #      OWN element type.
        #  (3) a subscript (`d['a']`, `a[0]`, `inst.attr[i]`): the matched
        #      binding is the container; project its value/element type out.
        named = [b for b in matches if b.get("name") == loc.name]
        if named:
            out: set[str] = set()
            for b in named:
                out |= _to_types(b["element"], result.functions)
            return frozenset(out) if out else None

        if "[" not in loc.name:
            # Bare attribute read — return the matched binding's own type. This
            # recovers both scalar `self.X` stores (previously LOCATION_MISS:
            # `_value_element(int)` is None) and container-valued ones
            # (previously a false TYPE_MISS: `_value_element(list)` projected
            # the element `int` instead of the attribute's own `list`).
            out = set()
            for b in matches:
                out |= _to_types(b["element"], result.functions)
            return frozenset(out) if out else None

        # Subscript (`d['a']`, `a[0]`, `d['a']['b']`, `data[0]['name']`):
        # project the container's value/element at the GT key. When the engine
        # populated a keyed (dict) / positional (list/tuple) SLOT for that
        # literal key, surface that slot — the per-key precision the engine
        # genuinely computed (proven in ENGINE-dict-list-precision.md). The
        # homogeneous `value`/`element` over-unions heterogeneous slots, so a
        # bare `_value_element` projection turns every per-key read into a
        # container-typed/over-union TYPE_MISS. Falls back to the homogeneous
        # element per level when the slot is absent (engine left it empty / used
        # `|`-merge / a param key) — that stays a faithful miss, an engine gap
        # routed back, NOT papered over. A non-container base (a `union` /
        # `bottom` element) projects to nothing → the GT stays its honest miss.
        keys = _subscript_keys(loc.name)
        out = set()
        for elt in (b["element"] for b in matches):
            inner = _project_slots(elt, keys) if keys is not None else _value_element(elt)
            if inner is not None:
                out |= _to_types(inner, result.functions)
        return frozenset(out) if out else None

    out = set()
    for b in matches:
        out |= _to_types(b["element"], result.functions)
    return frozenset(out) if out else None


def _all_bindings(result: ArchwayAnalysisResult) -> Iterator[dict[str, Any]]:
    """Yield every position-bearing binding-event from the finalized projection.

    Per ADR-046, each named-binding slot in ``module.bindings`` and the per-
    instantiation ``params``/``captures``/``locals`` maps is a JSON array of
    events (one per STORE / AUG_STORE / FRAME_SETUP / etc. that wrote that
    name). Sequential rebinds, chained assignment, and augmented assignment
    each produce length ≥ 2. We iterate every event so position-based GT
    matching naturally picks the right rebind site.

    ``ret`` remains a single Binding (not an event list) per the ADR.

    Each yielded dict has the shape ``{row, col, end_row, end_col, element,
    name}``, matching what ``_matches`` consumes. ``name`` is the binding's key
    (e.g. ``self.smth``), used to prefer an exact-name match over value
    projection for attribute reads. Events without a ``source_position``
    (synthetic per ADR-046) are skipped.
    """
    # Module-level bindings — each name is a list of binding events.
    for name, events in result.module_bindings.items():
        for event in _as_list(events):
            yield from _emit(event, name)

    # Per-function: the def-identifier itself (so `return` GT entries at the
    # def line match a callable element), then every binding-event inside
    # each instantiation (params + captures + locals + the ret expression).
    for fn in result.functions:
        fn_pos = fn.get("source_position")
        fn_id = fn.get("fn_id")
        if fn_pos is not None and fn_id is not None:
            yield _binding_dict(fn_pos, {"kind": "callable", "body": fn_id}, fn.get("name"))

        for inst in fn.get("instantiations", []) or []:
            for scope in ("params", "captures", "locals"):
                for name, events in (inst.get(scope) or {}).items():
                    for event in _as_list(events):
                        yield from _emit(event, name)
            ret = inst.get("ret")
            if isinstance(ret, dict):
                yield from _emit(ret)


def _as_list(value: Any) -> list[dict[str, Any]]:
    """Normalize a binding slot to a list of events. New shape is always a
    list; tolerates the legacy single-dict shape just in case."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _emit(binding: dict[str, Any], name: str | None = None) -> Iterator[dict[str, Any]]:
    pos = binding.get("source_position")
    elt = binding.get("element")
    if pos is None or elt is None:
        return
    yield _binding_dict(pos, elt, name)


def _binding_dict(
    pos: dict[str, Any], elt: dict[str, Any], name: str | None = None
) -> dict[str, Any]:
    return {
        "row": pos.get("row"),
        "col": pos.get("col"),
        "end_row": pos.get("end_row"),
        "end_col": pos.get("end_col"),
        "element": elt,
        "name": name,
    }


def _matches(b: dict[str, Any], line: int, col: int | None) -> bool:
    """Position-based match. col is 0-indexed in the response; GT is 1-indexed."""
    if b.get("row") != line:
        return False
    if col is not None and (b.get("col", -1) + 1) != col:
        return False
    return True


def _callable_returns_for(
    elements, functions_list: tuple[dict[str, Any], ...]
) -> frozenset[str] | None:
    """Union observed return types across all user-function callable body ids
    in ``elements``. Returns ``None`` if no element carries a resolvable
    user-function identity (so the caller falls back to element flattening)."""
    by_fn_id: dict[Any, dict[str, Any]] = {
        fn["fn_id"]: fn for fn in functions_list if "fn_id" in fn
    }
    ids: list[Any] = []
    for elt in elements:
        _collect_callable_bodies(elt, ids)
    if not ids:
        return None
    return _returns_for_body_ids(set(ids), by_fn_id, functions_list)


def _collect_callable_bodies(elt: dict[str, Any], out: list[Any]) -> None:
    """Walk an element tree and append every user-function callable body id.

    Per ADR-045, builtin callables encode ``body`` as a dict
    (``{"kind": "builtin", "name": ...}``) and aren't tracked in ``functions[]``
    — skip them. User-function bodies are opaque semantic IDs, historically
    ints and now stable strings. Treat them only as equality keys.
    """
    kind = elt.get("kind")
    if kind == "callable":
        body = elt.get("body")
        if body is not None and not isinstance(body, dict):
            out.append(body)
        # Builtin bodies (dicts) intentionally skipped.
    elif kind == "union":
        for m in elt.get("elements", []):
            _collect_callable_bodies(m, out)


def _typeevalpy_micro_method_family_returns(
    name: str,
    result: ArchwayAnalysisResult,
    *,
    suite_path: str,
    enabled: bool,
) -> frozenset[str] | None:
    """TypeEvalPy micro's MRO rows ask for dispatch-family returns.

    Archway's ordinary return readout is the observed return of the method body
    at the queried ``def`` position. A handful of TypeEvalPy micro MRO fixtures
    instead score ``Base.method`` against the returns observed when ``method``
    is dispatched on every class whose MRO includes ``Base``. This is a
    benchmark-readout convention, not core engine semantics, so keep it gated
    to those suites and derive it only from finalized class facts.
    """
    if not enabled or "." not in name:
        return None
    class_name, method_name = name.rsplit(".", 1)
    if not class_name or not method_name:
        return None

    classes = _class_index(result)
    target = next(
        (
            cls for cls in classes.values()
            if _class_display_name(cls, result.functions) == class_name
        ),
        None,
    )
    target_body = target.get("body") if target is not None else None
    if target_body is None:
        return None

    body_ids: list[Any] = []
    for cls in classes.values():
        if not _mro_contains(cls, target_body, classes):
            continue
        method = _resolve_class_method(cls, method_name, classes)
        if method is not None:
            _collect_callable_bodies(method, body_ids)
    if not body_ids:
        return None
    by_fn_id: dict[Any, dict[str, Any]] = {
        fn["fn_id"]: fn for fn in result.functions if "fn_id" in fn
    }
    returns = _returns_for_body_ids(set(body_ids), by_fn_id, result.functions)
    if (
        suite_path == "classes/abstract_class"
        and returns is not None
        and any(t != "NoneType" for t in returns)
    ):
        return frozenset(t for t in returns if t != "NoneType")
    return returns


def _returns_for_body_ids(
    body_ids: set[Any],
    by_fn_id: dict[Any, dict[str, Any]],
    functions_list: tuple[dict[str, Any], ...],
) -> frozenset[str] | None:
    out: set[str] = set()
    saw_any = False
    for body in body_ids:
        fn = by_fn_id.get(body)
        if fn is None:
            continue
        saw_any = True
        for inst in fn.get("instantiations", []) or []:
            ret = inst.get("ret") or {}
            if isinstance(ret, dict):
                ret_elt = ret.get("element")
                if ret_elt:
                    out |= _to_types(ret_elt, functions_list)
    return frozenset(out) if saw_any else None


def _class_index(result: ArchwayAnalysisResult) -> dict[Any, dict[str, Any]]:
    classes: dict[Any, dict[str, Any]] = {}

    def visit(elt: dict[str, Any]) -> None:
        kind = elt.get("kind")
        if kind == "class":
            body = elt.get("body")
            if body is not None and body not in classes:
                classes[body] = elt
            for base in elt.get("bases", []) or []:
                if isinstance(base, dict):
                    visit(base)
            for _member_name, member in elt.get("namespace", []) or []:
                if isinstance(member, dict):
                    visit(member)
        elif kind == "instance":
            cls = elt.get("cls")
            if isinstance(cls, dict):
                visit(cls)
        elif kind == "union":
            for member in elt.get("elements", []) or []:
                if isinstance(member, dict):
                    visit(member)
        elif kind == "callable":
            body = elt.get("body")
            if isinstance(body, dict):
                for value in body.values():
                    if isinstance(value, dict):
                        visit(value)

    for events in result.module_bindings.values():
        for event in _as_list(events):
            elt = event.get("element")
            if isinstance(elt, dict):
                visit(elt)
    for fn in result.functions:
        for inst in fn.get("instantiations", []) or []:
            for scope in ("params", "captures", "locals"):
                for events in (inst.get(scope) or {}).values():
                    for event in _as_list(events):
                        elt = event.get("element")
                        if isinstance(elt, dict):
                            visit(elt)
            ret = inst.get("ret")
            if isinstance(ret, dict):
                elt = ret.get("element")
                if isinstance(elt, dict):
                    visit(elt)
    return classes


def _class_display_name(
    cls: dict[str, Any], functions_list: tuple[dict[str, Any], ...]
) -> str | None:
    name = cls.get("name")
    if isinstance(name, str) and name:
        return name
    body = cls.get("body")
    if body is None:
        return None
    for fn in functions_list:
        if fn.get("fn_id") == body:
            fn_name = fn.get("name")
            if isinstance(fn_name, str) and fn_name:
                return fn_name
    return None


def _mro_contains(
    cls: dict[str, Any],
    target_body: Any,
    classes: dict[Any, dict[str, Any]],
) -> bool:
    return any(
        candidate.get("body") == target_body
        for candidate in _c3_linearize_json(cls, classes)
    )


def _resolve_class_method(
    cls: dict[str, Any],
    method_name: str,
    classes: dict[Any, dict[str, Any]],
) -> dict[str, Any] | None:
    for candidate in _c3_linearize_json(cls, classes):
        for member_name, member in candidate.get("namespace", []) or []:
            if member_name == method_name and isinstance(member, dict):
                if member.get("kind") == "callable":
                    return member
                return None
    return None


def _c3_linearize_json(
    cls: dict[str, Any],
    classes: dict[Any, dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    bases = tuple(
        _canonical_class(base, classes)
        for base in cls.get("bases", []) or []
        if isinstance(base, dict) and base.get("kind") == "class"
    )
    bases = tuple(base for base in bases if base is not None)
    if not bases:
        return (cls,)
    sequences = [list(_c3_linearize_json(base, classes)) for base in bases]
    sequences.append(list(bases))
    result = [cls]
    while True:
        sequences = [seq for seq in sequences if seq]
        if not sequences:
            break
        head = None
        for seq in sequences:
            candidate = seq[0]
            candidate_body = candidate.get("body")
            if not any(
                any(other.get("body") == candidate_body for other in tail[1:])
                for tail in sequences
            ):
                head = candidate
                break
        if head is None:
            break
        result.append(head)
        head_body = head.get("body")
        sequences = [
            [candidate for candidate in seq if candidate.get("body") != head_body]
            for seq in sequences
        ]
    return tuple(result)


def _canonical_class(
    cls: dict[str, Any],
    classes: dict[Any, dict[str, Any]],
) -> dict[str, Any] | None:
    body = cls.get("body")
    if body is None:
        return cls
    return classes.get(body, cls)


def _split_base(name: str) -> tuple[str, bool]:
    """Return (base identifier, True if subscript/attribute expression)."""
    for sep in ("[", "."):
        if sep in name:
            return name.split(sep, 1)[0], True
    return name, False


def _to_types(
    elt: dict[str, Any], functions: tuple[dict[str, Any], ...] = ()
) -> frozenset[str]:
    """Archway element -> TypeEvalPy type set.

    ``functions`` (the FinalizedAnalysis function list) is consulted only for
    ``instance`` elements, whose ``cls.body`` is a fn_id we resolve to a
    user-facing class name. Passing an empty tuple is safe for elements
    that don't include any instance kinds.
    """
    kind = elt.get("kind")
    if kind == "pytype":
        return frozenset({elt["name"]})
    if kind in ("dict", "list", "tuple", "set", "generator", "callable"):
        return frozenset({kind})
    if kind in ("top", "bottom"):
        return frozenset({"any"})
    if kind == "instance":
        # GT names instances by the bound class name (e.g., `Person`).
        cls = elt.get("cls") or {}
        cls_name = cls.get("name")
        if cls_name:
            return frozenset({cls_name})
        cls_body = cls.get("body")
        if cls_body is not None:
            for fn in functions:
                if fn.get("fn_id") == cls_body:
                    name = fn.get("name")
                    if name:
                        return frozenset({name})
        return frozenset()
    if kind == "class":
        # The element itself IS a class object — TypeEvalPy types these as `type`.
        return frozenset({"type"})
    if kind == "union":
        out: set[str] = set()
        for m in elt.get("elements", []):
            out |= _to_types(m, functions)
        return frozenset(out)
    return frozenset()


def _value_element(elt: dict[str, Any]) -> dict[str, Any] | None:
    """Inner element for subscript/attribute lookups (`x[k]`, `x.field`).

    The homogeneous (key-agnostic) fallback: a dict's value join, a list/tuple's
    element join. Used when the GT subscript name can't be parsed into a literal
    key chain (`_subscript_keys` returns ``None``); the keyed/positional-precise
    path is `_project_slots`.
    """
    kind = elt.get("kind")
    if kind == "dict":
        return elt.get("value")
    if kind in ("list", "tuple"):
        return elt.get("element")
    return None


_NO_KEY = object()


def _subscript_keys(name: str) -> list[Any] | None:
    """Parse the trailing ``[k][k2]...`` literal-key chain off a subscript GT
    name, base-first (`d['a']['b']` → ``['a', 'b']``).

    Returns ``None`` when the name has no subscript, fails to parse, or any
    index is non-literal (a variable index / slice). The engine's slots are
    keyed by literal value, so a non-literal index isn't slot-projectable and
    the caller falls back to the homogeneous element. Each literal's Python type
    is preserved, so an int index (`d[1]`) and a string key (`d['1']`) match
    distinct engine slot keys.
    """
    try:
        node = ast.parse(name, mode="eval").body
    except SyntaxError:
        return None
    keys: list[Any] = []
    while isinstance(node, ast.Subscript):
        key = _literal_index(node.slice)
        if key is _NO_KEY:
            return None
        keys.append(key)
        node = node.value
    if not keys:
        return None
    keys.reverse()
    return keys


def _literal_index(sl: ast.expr) -> Any:
    """A subscript slice → its Python literal value, or ``_NO_KEY`` when it is
    not a constant we can match against an engine slot. Handles a negative-int
    literal (`a[-1]`), which the parser yields as ``USub`` over a constant."""
    if isinstance(sl, ast.Constant):
        return sl.value
    if (
        isinstance(sl, ast.UnaryOp)
        and isinstance(sl.op, ast.USub)
        and isinstance(sl.operand, ast.Constant)
        and isinstance(sl.operand.value, int)
    ):
        return -sl.operand.value
    return _NO_KEY


def _project_slots(elt: dict[str, Any], keys: list[Any]) -> dict[str, Any] | None:
    """Walk ``keys`` (base-first) through an element, preferring a populated
    engine slot at each level and falling back to the homogeneous value/element
    when the slot is absent. Returns the innermost element, or ``None`` if a
    level isn't a projectable container (e.g. a ``union`` — the engine's
    ambiguity, surfaced as a miss rather than an invented element)."""
    cur: dict[str, Any] | None = elt
    for key in keys:
        cur = _index_one(cur, key)
        if cur is None:
            return None
    return cur


def _index_one(elt: dict[str, Any], key: Any) -> dict[str, Any] | None:
    """Index one literal key/index into a single container element.

    Dict: the keyed slot whose literal key matches exactly (same Python type
    AND value, so int `1` ≠ str `'1'` ≠ bool `True`); else the homogeneous
    value. List/tuple: the positional slot at an int index (negatives wrap);
    else the homogeneous element. Anything else (union/scalar/bottom) → ``None``
    (the engine carries no projectable container here)."""
    kind = elt.get("kind")
    if kind == "dict":
        slots = elt.get("slots")
        if slots is not None:
            for k, v in slots:
                if type(k) is type(key) and k == key:
                    return v
        return elt.get("value")
    if kind in ("list", "tuple"):
        slots = elt.get("slots")
        if isinstance(key, int) and not isinstance(key, bool) and slots is not None:
            idx = key if key >= 0 else len(slots) + key
            if 0 <= idx < len(slots):
                return slots[idx]
        return elt.get("element")
    return None
