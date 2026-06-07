"""Canonical Location ↔ TypeEvalPy-record mapping.

This module is the **single source of truth** for the mapping between our
internal `Location` model and TypeEvalPy's JSON schema
(`docs/TypeEvalPy_JSON_schema.py` in the vendored repo). Two callers share it:

  1. `archway_benchmarks.benchmarks.typeevalpy` — the harness adapter that
     emits TypeEvalPy-shape records from harness predictions.
  2. `upstream/target_tools/archway/src/typeevalpy_mapping.py` — a byte-
     identical copy that ships inside the upstream Docker image. The
     test `tests/test_upstream_sync.py` enforces parity.

If you change this file, run `scripts/sync_upstream_mapping.py` and commit
both copies. A drift is a bug — the upstream tool would score against a
slightly different schema than the harness scores itself on.

Self-contained: stdlib only, no archway_benchmarks-internal imports.

## col_offset convention (CRITICAL — read this before plugging in an engine)

TypeEvalPy's GT files use **1-indexed** `col_offset` (position of the first
character of the annotation's name in the source line, where the first
column is 1). Python's `ast` module reports `col_offset` **0-indexed**.

  Adapter contract: when projecting engine output to `MappedLocation.col`,
  the value MUST be 1-indexed (TypeEvalPy convention). If your engine emits
  ast-derived columns, **add 1** before passing to `MappedLocation`.

Empirically verified against `extras/TypeEvalPy/micro-benchmark/python_features/`
samples (see `tests/test_typeevalpy_col_convention.py`):

  source `a, b = func1, func2`            line 14:
      GT col_offset=1 -> identifier `a` (1-indexed first char)
      GT col_offset=4 -> identifier `b`
  source `def my_sum(a, b, *integers):`   line 4:
      GT col_offset=5  -> identifier `my_sum` (the function-return name)
      GT col_offset=12 -> identifier `a` (the first parameter)

The post-Oct-2025 strict scorer (`is_same_element`, commit `2f7c6056`) joins
on `col_offset`; getting this wrong by 1 produces silent LOCATION_MISS on
every annotation. The lenient (paper-era) scorer does not check `col_offset`,
so this convention only matters for the strict path — but Archway is the
only tool that meets the strict bar today, and an off-by-one would invert
that.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Kind = Literal["return", "parameter", "variable"]


@dataclass(frozen=True)
class MappedLocation:
    """Schema-neutral spine of a TypeEvalPy annotation site.

    The harness's `archway_benchmarks.types.Location` carries the same fields
    plus some harness-only metadata; we use a thin local dataclass here so
    the upstream copy doesn't depend on the harness package.

    `col` is **1-indexed** to match TypeEvalPy's GT convention — see the
    module docstring. If your engine emits ast-style 0-indexed columns,
    add 1 before constructing a `MappedLocation`. Setting `col=None` is
    valid (some tools omit columns) and will cause a LOCATION_MISS under
    the strict scorer.
    """

    file: str  # snippet-relative path like "assignments/tuple/main.py" or just "main.py"
    line: int  # 1-indexed
    col: int | None  # 1-indexed; None means "tool emitted no column" — strict-scorer LOCATION_MISS
    kind: Kind
    name: str  # function name (return), param name, variable name
    function: str | None = None  # enclosing function for params + scoped variables


def to_record(loc: MappedLocation, types: list[str] | frozenset[str] | set[str]) -> dict[str, Any]:
    """Project a (location, type-set) pair onto a TypeEvalPy JSON record.

    Output schema (per `docs/TypeEvalPy_JSON_schema.py`):
      - `file`: basename only (`main.py`), since each snippet is in its own dir
      - `line_number`, `col_offset` (0 if location's col is None)
      - `type`: sorted list of normalized type strings
      - `function` / `parameter` / `variable` depending on kind
    """
    rec: dict[str, Any] = {
        "file": loc.file.rsplit("/", 1)[-1],
        "line_number": loc.line,
        "col_offset": loc.col if loc.col is not None else 0,
        "type": sorted(types),
    }
    if loc.kind == "return":
        rec["function"] = loc.name
    elif loc.kind == "parameter":
        rec["function"] = loc.function
        rec["parameter"] = loc.name
    elif loc.kind == "variable":
        if loc.function is not None:
            rec["function"] = loc.function
        rec["variable"] = loc.name
    else:
        raise ValueError(f"unknown kind: {loc.kind!r}")
    return rec


def from_record(rec: dict[str, Any], file_id: str) -> tuple[MappedLocation, frozenset[str]]:
    """Inverse of `to_record`. Returns (MappedLocation, type-set).

    Kind discrimination follows the vendored scorer's `categorize_facts`
    (`src/result_analyzer/analysis_utils.py:80-104`):
      - has `function`, no `parameter`/`variable`   -> return
      - has `function` + `parameter`                -> parameter
      - has `variable` (with/without `function`)    -> variable
    """
    line = int(rec["line_number"])
    col_raw = rec.get("col_offset")
    col = int(col_raw) if col_raw is not None else None
    types = frozenset(rec.get("type", []))

    if "parameter" in rec and "function" in rec:
        loc = MappedLocation(
            file=file_id,
            line=line,
            col=col,
            kind="parameter",
            name=rec["parameter"],
            function=rec["function"],
        )
    elif "variable" in rec:
        loc = MappedLocation(
            file=file_id,
            line=line,
            col=col,
            kind="variable",
            name=rec["variable"],
            function=rec.get("function"),
        )
    elif "function" in rec:
        loc = MappedLocation(
            file=file_id,
            line=line,
            col=col,
            kind="return",
            name=rec["function"],
            function=None,
        )
    else:
        raise ValueError(f"unrecognized TypeEvalPy record shape: {rec!r}")

    return loc, types
