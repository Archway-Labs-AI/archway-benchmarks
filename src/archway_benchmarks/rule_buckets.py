"""Rule-bucket classifier for TypeEvalPy annotations.

Buckets follow Ben's expression-typer build order:

  A1 — scalars                : int, str
  A2 — function-reference     : callable
  A3 — containers             : list, dict, tuple
  A4 — float/bool/None        : float, bool, nonetype
  A5 — constructor -> class   : anything else (post-normalization)

An annotation's bucket is determined by its **ground-truth** type set,
not by what the engine predicted. Buckets are first-match in the order
above; an annotation whose GT is `{"int", "callable"}` lands in A1.

Why this exists: aggregate "covered EXACT %" is a single number that
hides which inference rule is landing. Bucket × kind tells Ben where the
expression-typer is paying off and where it isn't — "callable 40%
caught, int 85%, containers 0%" is the build-time triage view.

Cross-tab axis: TypeEvalPy kinds (LV / FR / FP). LV + FR share the
expression-typer and FP is the separate hard pass.
"""
from __future__ import annotations

from typing import Iterable, Literal

BucketName = Literal["A1", "A2", "A3", "A4", "A5"]

BUCKETS: tuple[BucketName, ...] = ("A1", "A2", "A3", "A4", "A5")

BUCKET_TYPES: dict[BucketName, frozenset[str]] = {
    "A1": frozenset({"int", "str"}),
    "A2": frozenset({"callable"}),
    "A3": frozenset({"list", "dict", "tuple"}),
    "A4": frozenset({"float", "bool", "nonetype"}),
    # A5 is the residual — class names, post-normalization (lowercased).
}

BUCKET_LABELS: dict[BucketName, str] = {
    "A1": "A1 · scalars (int, str)",
    "A2": "A2 · callable",
    "A3": "A3 · containers (list, dict, tuple)",
    "A4": "A4 · float/bool/None",
    "A5": "A5 · constructor → class name",
}


def classify(gt_types: Iterable[str]) -> BucketName:
    """Return the rule bucket for a GT type set.

    First-match precedence A1 → A5; A5 is the residual catch-all so the
    classifier is total."""
    types = {t.lower() for t in gt_types}
    for bucket in ("A1", "A2", "A3", "A4"):
        if types & BUCKET_TYPES[bucket]:  # type: ignore[index]
            return bucket  # type: ignore[return-value]
    return "A5"


def empty_bucket_kind_table() -> dict[str, dict[str, int]]:
    """`{bucket: {kind: 0}}` skeleton, zero-initialised across the full grid."""
    return {b: {"return": 0, "parameter": 0, "variable": 0} for b in BUCKETS}
