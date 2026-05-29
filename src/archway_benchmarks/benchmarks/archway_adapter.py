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
            types = _lookup_predicted_types(gt, result.positioned, result.functions)
            if types is None:
                continue
            out.append(Annotation(location=gt.location, types=types))
        return out


def _lookup_predicted_types(
    gt: Annotation,
    positioned: tuple[dict[str, Any], ...],
    functions: dict[str, dict[str, Any]],
) -> frozenset[str] | None:
    loc = gt.location
    base, is_indirect = _split_base(loc.name)
    for w in positioned:
        if w.get("wire_name") != base:
            continue
        if w.get("row") != loc.line:
            continue
        if loc.col is not None and (w.get("col", -1) + 1) != loc.col:
            continue
        elt = w.get("element", {})
        if is_indirect:
            inner = _value_element(elt)
            return _to_types(inner) if inner is not None else None
        # GT `function:` entries (kind="return") want the return type of the
        # callable, not the fact that it's callable. Look up the body id in
        # the signatures map and union all observed returns. Falls back to
        # element-level types when no signature is observed (function never
        # called) or the wire isn't callable.
        if loc.kind == "return":
            returns = _callable_returns(elt, functions)
            if returns is not None:
                return returns
        return _to_types(elt)
    return None


def _callable_returns(
    elt: dict[str, Any], functions: dict[str, dict[str, Any]]
) -> frozenset[str] | None:
    """Union of all observed return types for the callable(s) in `elt`.

    Returns ``None`` if the element carries no callable identity at all,
    so the caller can fall back to element-level flattening.
    """
    ids: list[Any] = []
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
    if not saw_any:
        # Element is a callable but the function was never called — no
        # observed return. Surface as "no prediction" so the caller falls
        # back to the static element-level types ("callable").
        return None
    return frozenset(out)


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
