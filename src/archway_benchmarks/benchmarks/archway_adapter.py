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
- ``Top``/``Bottom`` map to ``"any"``.
- ``Union`` produces a ``frozenset`` of all members' flattened forms; the
  scorer intersects with GT's type set.
- For ``return`` GT entries, the binding at the def-identifier position carries
  a callable element; we resolve its body id in ``functions[]`` and union the
  observed ``inst.ret.element`` types. Builtin callable bodies (``body`` is a
  dict per ADR-045) carry no instantiation log and are skipped.
"""
from __future__ import annotations

from typing import Any, Iterator

from archway_benchmarks.benchmarks.base import AnalysisResultAdapter
from archway_benchmarks.engines.archway import ArchwayAnalysisResult
from archway_benchmarks.types import Annotation, Snippet


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
            types = _lookup_predicted_types(gt, result)
            if types is None:
                continue
            out.append(Annotation(location=gt.location, types=types))
        return out


def _lookup_predicted_types(
    gt: Annotation, result: ArchwayAnalysisResult
) -> frozenset[str] | None:
    loc = gt.location
    base, is_indirect = _split_base(loc.name)
    matches = [b for b in _all_bindings(result) if _matches(b, loc.line, loc.col)]
    if not matches:
        return None

    if is_indirect:
        out: set[str] = set()
        for elt in (b["element"] for b in matches):
            inner = _value_element(elt)
            if inner is not None:
                out |= _to_types(inner, result.functions)
        return frozenset(out) if out else None

    # GT `return` entries want the function's observed return types. The
    # def identifier binding carries the callable; resolve through fn_id to
    # `functions[].instantiations[].ret`. Falls back to element-flatten when
    # the callable has no instantiations (uninstantiated function — empty
    # returns) or carries a builtin body (no per-call log per ADR-045).
    if loc.kind == "return":
        returns = _callable_returns_for(
            (b["element"] for b in matches), result.functions
        )
        if returns is not None:
            return returns

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

    Each yielded dict has the shape ``{row, col, end_row, end_col, element}``,
    matching what ``_matches`` consumes. Events without a ``source_position``
    (synthetic per ADR-046) are skipped.
    """
    # Module-level bindings — each name is a list of binding events.
    for _, events in result.module_bindings.items():
        for event in _as_list(events):
            yield from _emit(event)

    # Per-function: the def-identifier itself (so `return` GT entries at the
    # def line match a callable element), then every binding-event inside
    # each instantiation (params + captures + locals + the ret expression).
    for fn in result.functions:
        fn_pos = fn.get("source_position")
        fn_id = fn.get("fn_id")
        if fn_pos is not None and fn_id is not None:
            yield _binding_dict(fn_pos, {"kind": "callable", "body": fn_id})

        for inst in fn.get("instantiations", []) or []:
            for scope in ("params", "captures", "locals"):
                for _, events in (inst.get(scope) or {}).items():
                    for event in _as_list(events):
                        yield from _emit(event)
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


def _emit(binding: dict[str, Any]) -> Iterator[dict[str, Any]]:
    pos = binding.get("source_position")
    elt = binding.get("element")
    if pos is None or elt is None:
        return
    yield _binding_dict(pos, elt)


def _binding_dict(pos: dict[str, Any], elt: dict[str, Any]) -> dict[str, Any]:
    return {
        "row": pos.get("row"),
        "col": pos.get("col"),
        "end_row": pos.get("end_row"),
        "end_col": pos.get("end_col"),
        "element": elt,
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
    by_fn_id: dict[int, dict[str, Any]] = {
        fn["fn_id"]: fn for fn in functions_list if "fn_id" in fn
    }
    ids: list[int] = []
    for elt in elements:
        _collect_callable_bodies(elt, ids)
    if not ids:
        return None
    out: set[str] = set()
    saw_any = False
    for body in ids:
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


def _collect_callable_bodies(elt: dict[str, Any], out: list[int]) -> None:
    """Walk an element tree and append every user-function callable body id.

    Per ADR-045, builtin callables encode ``body`` as a dict
    (``{"kind": "builtin", "name": ...}``) and aren't tracked in ``functions[]``
    — skip them. User-function bodies are ints (fn_id).
    """
    kind = elt.get("kind")
    if kind == "callable":
        body = elt.get("body")
        if isinstance(body, int):
            out.append(body)
        # Builtin bodies (dicts) intentionally skipped.
    elif kind == "union":
        for m in elt.get("elements", []):
            _collect_callable_bodies(m, out)


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
    if kind in ("dict", "list", "tuple", "callable"):
        return frozenset({kind})
    if kind in ("top", "bottom"):
        return frozenset({"any"})
    if kind == "instance":
        # GT names instances by the bound class name (e.g., `Person`).
        cls = elt.get("cls") or {}
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
    """Inner element for subscript/attribute lookups (`x[k]`, `x.field`)."""
    kind = elt.get("kind")
    if kind == "dict":
        return elt.get("value")
    if kind in ("list", "tuple"):
        return elt.get("element")
    return None
