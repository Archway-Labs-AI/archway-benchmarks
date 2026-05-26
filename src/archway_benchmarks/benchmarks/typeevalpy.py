"""TypeEvalPy benchmark.

Loads snippets from `vendor/TypeEvalPy/micro-benchmark/python_features/**/`,
parses ground-truth JSON into harness-native `Annotation`s, and exposes a
`to_tool_format` round-trip so we can hand predictions back to TypeEvalPy's
scorer (Layer A).

Scoring is wired in `archway_benchmarks.scoring.typeevalpy` (Phase 3).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archway_benchmarks.benchmarks.base import Benchmark
from archway_benchmarks.types import Annotation, Location, Scores, Snippet

# Resolved at import time so the package can be installed editable from
# anywhere; we walk up from this module to the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CORPUS = _REPO_ROOT / "vendor" / "TypeEvalPy" / "micro-benchmark" / "python_features"


class TypeEvalPyBenchmark(Benchmark):
    name = "typeevalpy"

    def __init__(self, corpus_root: Path | None = None) -> None:
        self.corpus_root = Path(corpus_root) if corpus_root else _DEFAULT_CORPUS
        if not self.corpus_root.exists():
            raise FileNotFoundError(
                f"TypeEvalPy corpus not found at {self.corpus_root}. "
                "Initialize the submodule: `git submodule update --init --recursive`."
            )
        self._snippets: list[Snippet] | None = None

    # ----- Benchmark API -----

    def load(self) -> list[Snippet]:
        if self._snippets is not None:
            return self._snippets

        snippets: list[Snippet] = []
        for src_path in sorted(self.corpus_root.rglob("main.py")):
            gt_path = src_path.with_name("main_gt.json")
            if not gt_path.exists():
                continue
            suite_path = src_path.parent.relative_to(self.corpus_root).as_posix()
            snippets.append(self._load_snippet(src_path, gt_path, suite_path))

        self._snippets = snippets
        return snippets

    def ground_truth(self) -> dict[Location, frozenset[str]]:
        out: dict[Location, frozenset[str]] = {}
        for snip in self.load():
            for ann in snip.annotations:
                out[ann.location] = ann.types
        return out

    def to_tool_format(
        self, predictions: dict[Location, frozenset[str]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Project predictions back into TypeEvalPy's per-snippet JSON shape.

        Returns `{suite_path: list[record]}`. Each `record` matches the
        TypeEvalPy schema (`docs/TypeEvalPy_JSON_schema.py`). Callers write
        each value to `<corpus_root>/<suite_path>/main_result.json` to feed
        TypeEvalPy's scorer.
        """
        grouped: dict[str, list[dict[str, Any]]] = {}
        for loc, types in predictions.items():
            suite_path, _, _ = loc.file.rpartition("/")
            record = _location_to_record(loc, types)
            grouped.setdefault(suite_path, []).append(record)
        return grouped

    def score(self, predictions: dict[Location, frozenset[str]]) -> Scores:
        # Phase 3 wires the real scorer. Importing here avoids a circular
        # dependency since scoring imports Benchmark types.
        from archway_benchmarks.scoring.typeevalpy import score_predictions

        return score_predictions(self, predictions)

    # ----- internals -----

    def _load_snippet(
        self, src_path: Path, gt_path: Path, suite_path: str
    ) -> Snippet:
        source = src_path.read_text()
        with gt_path.open() as f:
            raw = json.load(f)

        file_id = f"{suite_path}/main.py"
        annotations = tuple(_record_to_annotation(rec, file_id) for rec in raw)
        return Snippet(
            benchmark=self.name,
            suite_path=suite_path,
            file_path=file_id,
            source=source,
            annotations=annotations,
        )


# ----- record <-> Annotation conversion -----

def _record_to_annotation(rec: dict[str, Any], file_id: str) -> Annotation:
    """Project a TypeEvalPy schema record onto our Location/Annotation.

    Kind discrimination follows the scorer's `categorize_facts`
    (`vendor/TypeEvalPy/src/result_analyzer/analysis_utils.py:80-104`):
      - has `function`, no `parameter`/`variable`  -> return
      - has `function` + `parameter`               -> parameter
      - has `variable` (with/without `function`)   -> variable
    """
    line = int(rec["line_number"])
    col = int(rec["col_offset"])
    types = frozenset(rec.get("type", []))

    if "parameter" in rec and "function" in rec:
        loc = Location(
            file=file_id,
            line=line,
            col=col,
            kind="parameter",
            name=rec["parameter"],
            function=rec["function"],
        )
    elif "variable" in rec:
        loc = Location(
            file=file_id,
            line=line,
            col=col,
            kind="variable",
            name=rec["variable"],
            function=rec.get("function"),
        )
    elif "function" in rec:
        loc = Location(
            file=file_id,
            line=line,
            col=col,
            kind="return",
            name=rec["function"],
            function=None,
        )
    else:
        raise ValueError(f"Unrecognized TypeEvalPy record shape: {rec!r}")

    return Annotation(location=loc, types=types)


def _location_to_record(loc: Location, types: frozenset[str]) -> dict[str, Any]:
    """Inverse of `_record_to_annotation`. The emitted `file` is the basename
    (`main.py`), matching what TypeEvalPy expects per snippet directory."""
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
    return rec
