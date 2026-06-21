"""A plausible Archway analysis-engine output shape, for harness validation.

The real engine is out of scope for the harness; this fixture documents the
agreed contract (an `AnalysisResult` carrying typed locations) so we can
exercise the **real adapter → scorer → store** path without the real engine
in the room. The shape is what the harness assumes the real engine will emit;
treat it as the integration contract.

This module ships with the test suite, NOT in production code paths.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from archway_benchmarks.benchmarks.base import AnalysisResultAdapter
from archway_benchmarks.types import Annotation, Location, Snippet


# ----- Contract: the shape we expect the real engine to emit ------------

@dataclass(frozen=True)
class ArchwayInferredAnnotation:
    """One annotation site, as projected from Archway's categorical IR.

    The engine emits these post-analysis; the adapter projects them onto
    the harness's `Location` keyspace and into TypeEvalPy's join keys.
    """

    file: str           # snippet-relative path (e.g. "args/multiple/main.py")
    line: int           # 1-based
    col: int | None     # 0-based; None for tools/engines that can't supply it
    function: str | None  # enclosing function (None = module scope)
    parameter: str | None  # set when this is a function-parameter annotation
    variable: str | None   # set when this is a variable annotation
    types: tuple[str, ...]  # normalized type names (already lowercased)


@dataclass
class ArchwayAnalysisResult:
    """Top-level analysis output for a single snippet.

    Opaque to the harness — only `ArchwayAnalysisResultAdapter` knows the
    shape. If the real engine emits a richer payload (IR graphs, side-effect
    metadata, etc.), only the adapter changes; the rest of the harness is
    blissfully unaware.
    """

    snippet_path: str
    annotations: list[ArchwayInferredAnnotation] = field(default_factory=list)


# ----- Adapter: the ONLY code that knows the engine output's shape -------

class ArchwayAnalysisResultAdapter(AnalysisResultAdapter):
    """Projects an `ArchwayAnalysisResult` onto harness-native `Annotation`s.

    The crucial mapping work — fragmenting one annotation across the right
    `Location.kind` (return/parameter/variable) plus the join-key field
    discipline — happens here, never elsewhere.
    """

    def to_annotations(
        self, result: Any, snippet: Snippet
    ) -> list[Annotation]:
        if not isinstance(result, ArchwayAnalysisResult):
            raise TypeError(
                f"ArchwayAnalysisResultAdapter only handles ArchwayAnalysisResult; "
                f"got {type(result).__name__}"
            )

        annotations: list[Annotation] = []
        for entry in result.annotations:
            kind: str
            name: str
            function_field: str | None

            if entry.parameter is not None and entry.function is not None:
                kind, name = "parameter", entry.parameter
                function_field = entry.function
            elif entry.variable is not None:
                kind, name = "variable", entry.variable
                function_field = entry.function  # may be None at module scope
            elif entry.function is not None:
                kind, name = "return", entry.function
                function_field = None
            else:
                # Engine emitted a malformed location — skip rather than
                # crash. This shows up as a missing prediction (LOCATION_MISS
                # in scoring), which is the right signal for the team.
                continue

            location = Location(
                file=snippet.file_path,  # globally-unique suite-relative path
                line=entry.line,
                col=entry.col,
                kind=kind,
                name=name,
                function=function_field,
            )
            annotations.append(Annotation(location=location, types=frozenset(entry.types)))
        return annotations


# ----- Fixture builder: a hand-authored AnalysisResult with planted defects -

def build_args_multiple_fixture(snippet: Snippet) -> ArchwayAnalysisResult:
    """Return a hand-crafted `ArchwayAnalysisResult` for `args/multiple`.

    Mirrors the GT for that snippet but with deliberate defects to exercise
    the bucket classifier:

      - **EXACT** rows: most annotations are correct.
      - **LOCATION_MISS (col_offset off-by-one):** `my_sum`'s return at
        col 5 is reported at col 4. The type is right but the join key
        differs, so the scorer correctly cannot match this to GT.
      - **LOCATION_MISS (line off-by-one):** `func`'s return at line 11
        is reported at line 12. Same story.
      - **LOCATION_MISS (parameter renamed):** `func(a)`'s param `a` is
        reported with `parameter="x"`. Right scope and line, wrong name —
        no GT entry has that name, so this is plumbing, not a wrong type.
      - **TYPE_MISS:** `my_sum`'s parameter `a` is reported as `str` instead
        of `int`. Right location, wrong type.

    Returned shape is opaque to the rest of the test — only the adapter
    above can read it.
    """
    file = snippet.file_path  # e.g. "args/multiple/main.py"

    # Every GT entry in the same order as `main_gt.json`, with the defects
    # encoded inline as comments.
    annotations: list[ArchwayInferredAnnotation] = [
        # GT: line 4 col 5, return my_sum -> ["int"]
        # Defect (LOCATION_MISS, col off-by-one): reported at col 4
        ArchwayInferredAnnotation(file=file, line=4, col=4, function="my_sum",
                                  parameter=None, variable=None, types=("int",)),

        # GT: line 4 col 12, parameter a of my_sum -> ["int"]
        # Defect (TYPE_MISS): right location, wrong type
        ArchwayInferredAnnotation(file=file, line=4, col=12, function="my_sum",
                                  parameter="a", variable=None, types=("str",)),

        # GT: line 4 col 15, parameter b of my_sum -> ["int"]  (EXACT)
        ArchwayInferredAnnotation(file=file, line=4, col=15, function="my_sum",
                                  parameter="b", variable=None, types=("int",)),

        # GT: line 4 col 19, parameter integers of my_sum -> ["tuple"]  (EXACT)
        ArchwayInferredAnnotation(file=file, line=4, col=19, function="my_sum",
                                  parameter="integers", variable=None, types=("tuple",)),

        # GT: line 5 col 5, variable result in my_sum -> ["int"]  (EXACT)
        ArchwayInferredAnnotation(file=file, line=5, col=5, function="my_sum",
                                  parameter=None, variable="result", types=("int",)),

        # GT: line 6 col 9, variable x in my_sum -> ["int"]  (EXACT)
        ArchwayInferredAnnotation(file=file, line=6, col=9, function="my_sum",
                                  parameter=None, variable="x", types=("int",)),

        # GT: line 7 col 9, variable result in my_sum -> ["int"]  (EXACT)
        ArchwayInferredAnnotation(file=file, line=7, col=9, function="my_sum",
                                  parameter=None, variable="result", types=("int",)),

        # GT: line 11 col 5, return func -> ["int"]
        # Defect (LOCATION_MISS, line off-by-one): reported at line 12
        ArchwayInferredAnnotation(file=file, line=12, col=5, function="func",
                                  parameter=None, variable=None, types=("int",)),

        # GT: line 11 col 10, parameter a of func -> ["callable"]
        # Defect (LOCATION_MISS, parameter renamed): reported as "x"
        ArchwayInferredAnnotation(file=file, line=11, col=10, function="func",
                                  parameter="x", variable=None, types=("callable",)),

        # GT: line 15 col 1, variable b -> ["int"]  (EXACT)
        ArchwayInferredAnnotation(file=file, line=15, col=1, function=None,
                                  parameter=None, variable="b", types=("int",)),
    ]

    return ArchwayAnalysisResult(snippet_path=snippet.suite_path, annotations=annotations)


# ----- A1+A2 reference fixture: a clean known-good target ------------------

def build_a1_a2_reference_fixture(snippet) -> ArchwayAnalysisResult:
    """A clean fixture that predicts every A1 (int/str) and A2 (callable) GT
    annotation in the snippet correctly, leaving A3/A4/A5 unpredicted.

    Purpose: compare a narrow scalar/callable reference against a real run.
    If a run scores below the fixture, the gap is likely in the corresponding
    inference logic; if at/above, the harness + coordinate plumbing are sound.

    This emits the real `AnalysisResult` shape and runs through the real
    adapter and scorer (not the noise stub).
    """
    from archway_benchmarks.rule_buckets import classify

    annotations: list[ArchwayInferredAnnotation] = []
    for ann in snippet.annotations:
        bucket = classify(ann.types)
        if bucket not in ("A1", "A2"):
            continue  # leave unpredicted — later passes will handle these

        loc = ann.location
        if loc.kind == "return":
            entry = ArchwayInferredAnnotation(
                file=snippet.file_path, line=loc.line, col=loc.col,
                function=loc.name, parameter=None, variable=None,
                types=tuple(sorted(ann.types)),
            )
        elif loc.kind == "parameter":
            entry = ArchwayInferredAnnotation(
                file=snippet.file_path, line=loc.line, col=loc.col,
                function=loc.function, parameter=loc.name, variable=None,
                types=tuple(sorted(ann.types)),
            )
        elif loc.kind == "variable":
            entry = ArchwayInferredAnnotation(
                file=snippet.file_path, line=loc.line, col=loc.col,
                function=loc.function, parameter=None, variable=loc.name,
                types=tuple(sorted(ann.types)),
            )
        else:
            continue
        annotations.append(entry)

    return ArchwayAnalysisResult(snippet_path=snippet.suite_path, annotations=annotations)


# ----- Engine pair: deterministic, no GT shortcut ------------------------

@dataclass(frozen=True)
class _MarkerTranslation:
    """Trivial Translation marker; the engine carries the analysis result."""

    snippet_path: str


class FixtureTranslationEngine:
    """A no-op translation engine for the seam test. Returns a marker that
    the analysis engine matches against to surface its pre-built result."""

    name = "fixture-translation"

    def translate(self, source: str, path: str) -> _MarkerTranslation:
        return _MarkerTranslation(snippet_path=path)


class FixtureAnalysisEngine:
    """Returns a pre-built `ArchwayAnalysisResult` keyed by snippet path.

    No ground truth is consulted; the result is whatever the fixture builder
    supplied. This is the path the real engine will follow — *not* the
    GT-shortcut stub.
    """

    name = "fixture-analysis"

    def __init__(self, results_by_path: dict[str, ArchwayAnalysisResult]) -> None:
        self._results = results_by_path

    def analyze(self, translation: Any) -> ArchwayAnalysisResult:
        if not isinstance(translation, _MarkerTranslation):
            raise TypeError(
                "FixtureAnalysisEngine expects _MarkerTranslation from FixtureTranslationEngine"
            )
        try:
            return self._results[translation.snippet_path]
        except KeyError:
            # Snippet has no fixture — represent as "no analysis output",
            # which the runner correctly persists as LOCATION_MISS for every
            # GT annotation in that snippet.
            return ArchwayAnalysisResult(snippet_path=translation.snippet_path, annotations=[])
