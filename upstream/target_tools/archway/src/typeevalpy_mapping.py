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
    """

    file: str  # snippet-relative path like "assignments/tuple/main.py" or just "main.py"
    line: int
    col: int | None  # may be None for tools that omit col_offset (LOCATION_MISS at scoring)
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
