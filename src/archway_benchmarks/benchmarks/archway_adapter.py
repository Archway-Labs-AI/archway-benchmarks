"""Adapter: ``ArchwayAnalysisResult`` -> ``list[Annotation]``.

The only code in the harness that knows the analysis server's response shape.
Walks the snippet's ground-truth annotations and, for each one, looks up the
matching Archway positioned-wire prediction and emits an ``Annotation``
keyed at the GT's ``Location`` carrying the predicted type set.

The lookup is GT-keyed (not engine-keyed) by design — the runner's join is
``Location``-based, so we only emit predictions at locations the GT actually
asks about. Extra wires Archway produces but GT doesn't track are dropped here.
Switching to engine-keyed enumeration (so we can also surface spurious
predictions) is a follow-up.

Post-processing applied:

- Archway's wire ``col`` is 0-indexed (Python AST convention); the harness
  ``Location.col`` is 1-indexed. We add 1 when matching.
- Compound Archway types (``dict``, ``list``, ``tuple``) flatten to TypeEvalPy's
  flat strings.
- GT entries for subscript expressions (``a[0]``, ``d['key']``) resolve to the
  parent wire's value/element type.
- GT entries for attribute expressions (``self.x``) resolve to the base wire's
  inner element. Best-effort; rich attribute support is TBD.
- ``Top``/``Bottom`` map to ``"any"``.
- ``Union`` produces a ``frozenset`` of all members' flattened forms; the
  scorer intersects with GT's type set.
"""
from __future__ import annotations

from typing import Any

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
    matches = [w for w in _all_wires(result) if _matches(w, base, loc.line, loc.col)]
    if not matches:
        return None

    if is_indirect:
        out: set[str] = set()
        for elt in (w["element"] for w in matches):
            inner = _value_element(elt)
            if inner is not None:
                out |= _to_types(inner)
        return frozenset(out) if out else None

    # GT `function:` entries (kind="return") want the return type of the
    # callable. Look up the body id in functions[] and union all observed
    # returns; fall back to element-level types when not callable or never
    # called.
    if loc.kind == "return":
        returns = _callable_returns_for(
            (w["element"] for w in matches), result.functions
        )
        if returns is not None:
            return returns

    out = set()
    for w in matches:
        out |= _to_types(w["element"])
    return frozenset(out) if out else None


def _all_wires(result: ArchwayAnalysisResult):
    """Walk every named-or-unnamed wire that could match a GT lookup.

    Includes top-level positioned wires AND per-instantiation body wires
    surfaced under ``functions[].instantiations[].wires``. The body wires
    expose parameters, locals, and intermediates with their source
    positions, so the adapter doesn't need a separate code path for
    parameter or use-site lookups — they all flow through the same
    ``(name, line, col)`` match.

    ``unbound_cell`` wires are skipped — those carry Bottom by design
    (pre-allocation in the cell model) and would otherwise drag a real
    typing into ``any`` via union.
    """
    for w in result.positioned:
        yield w
    for fn in result.functions.values():
        for inst in fn.get("instantiations", []) or []:
            for w in inst.get("wires", []) or []:
                if w.get("role") == "unbound_cell":
                    continue
                pos = w.get("position") or {}
                yield {
                    "wire_name": w.get("name"),
                    "row": pos.get("row"),
                    "col": pos.get("col"),
                    "end_row": pos.get("end_row"),
                    "end_col": pos.get("end_col"),
                    "element": w.get("element", {}),
                    "_role": w.get("role"),
                }


def _matches(w: dict[str, Any], name: str, line: int, col: int | None) -> bool:
    if w.get("wire_name") != name:
        return False
    if w.get("row") != line:
        return False
    if col is not None and (w.get("col", -1) + 1) != col:
        return False
    return True


def _callable_returns_for(
    elements, functions: dict[str, dict[str, Any]]
) -> frozenset[str] | None:
    """Union observed return types across all callable body ids in
    `elements`. Returns ``None`` if no element carries a callable identity,
    so the caller can fall back to element-level flattening."""
    ids: list[Any] = []
    for elt in elements:
        _collect_callable_bodies(elt, ids)
    if not ids:
        return None
    out: set[str] = set()
    saw_any = False
    for body in ids:
        sig = functions.get(str(body))
        if not sig:
            continue
        saw_any = True
        for inst in sig.get("instantiations", []):
            out |= _to_types(inst.get("ret", {}))
    return frozenset(out) if saw_any else None


def _collect_callable_bodies(elt: dict[str, Any], out: list[Any]) -> None:
    """Walk an element tree and append every Callable body id encountered."""
    kind = elt.get("kind")
    if kind == "callable":
        out.append(elt.get("body"))
    elif kind == "union":
        for m in elt.get("elements", []):
            _collect_callable_bodies(m, out)


def _split_base(name: str) -> tuple[str, bool]:
    """Return (base identifier, True if subscript/attribute expression)."""
    for sep in ("[", "."):
        if sep in name:
            return name.split(sep, 1)[0], True
    return name, False


def _to_types(elt: dict[str, Any]) -> frozenset[str]:
    """Archway element -> TypeEvalPy type set."""
    kind = elt.get("kind")
    if kind == "pytype":
        return frozenset({elt["name"]})
    if kind in ("dict", "list", "tuple", "callable"):
        return frozenset({kind})
    if kind in ("top", "bottom"):
        return frozenset({"any"})
    if kind == "union":
        out: set[str] = set()
        for m in elt.get("elements", []):
            out |= _to_types(m)
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
