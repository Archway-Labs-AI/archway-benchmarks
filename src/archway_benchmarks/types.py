"""Core types shared across the harness.

The `Location`/`Annotation` pair is the spine of the harness: every prediction
and every ground-truth fact is keyed by `Location`, and scoring is a join over
those keys. Keep this module dependency-free.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Kind = Literal["return", "parameter", "variable"]


@dataclass(frozen=True)
class Location:
    file: str
    line: int
    col: int | None
    kind: Kind
    name: str  # function name (return), param name, or variable name
    function: str | None = None  # enclosing function for parameters / scoped vars


@dataclass(frozen=True)
class Annotation:
    location: Location
    types: frozenset[str]  # set — TypeEvalPy ground truth allows alternatives


@dataclass(frozen=True)
class Snippet:
    """A single benchmark snippet: the file under test + its ground truth."""

    benchmark: str
    suite_path: str  # e.g. "python_features/assignments/tuple"
    file_path: str  # absolute path to the source file
    source: str
    annotations: tuple[Annotation, ...]  # ground truth for this snippet


@dataclass(frozen=True)
class Scores:
    """Layer-A scoring output. Mirrors TypeEvalPy's metrics exactly.

    `files_*` are per-file binary counts (TypeEvalPy's canonical metric).
    `annotations_*` are per-annotation derived metrics (Layer-B convenience).
    """

    total_snippets: int
    total_annotations: int

    # TypeEvalPy canonical: per-file binary, summed
    files_sound: int
    files_complete: int

    # exact-match annotation counts (overall and per kind)
    exact_total: int
    exact_by_kind: dict[str, int]  # {"return": N, "parameter": N, "variable": N}
    exact_by_category: dict[str, int]  # one entry per TypeEvalPy feature category

    # derived per-annotation rates (Layer-B; for error analysis)
    annotation_precision: float
    annotation_recall: float
