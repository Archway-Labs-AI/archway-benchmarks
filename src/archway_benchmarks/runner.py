"""Runner — orchestrates the per-snippet pipeline and persists a run.

Pipeline per snippet:
    source -> translate -> analyze -> adapter.to_annotations -> predictions
Then per-snippet three-bucket scoring; aggregated to two `Scores`:
  - `all`     — over the whole corpus (leaderboard-comparable)
  - `covered` — over the snippets the translation engine actually attempted

With the stub trio, every snippet is COVERED, so the two `Scores` are equal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from archway_benchmarks.benchmarks.typeevalpy import (
    TypeEvalPyBenchmark,
    _location_to_record,
)
from archway_benchmarks.coverage import CoverageStatus, UnsupportedSourceError
from archway_benchmarks.engines.base import AnalysisEngine, TranslationEngine
from archway_benchmarks.benchmarks.base import AnalysisResultAdapter
from archway_benchmarks.scoring.typeevalpy import (
    SnippetScores,
    _aggregate,
    score_snippet,
)
from archway_benchmarks.store import (
    connect,
    create_run,
    record_scores,
    record_snippet,
    record_snippet_scores,
)
from archway_benchmarks.types import Snippet


CoverageProbe = Callable[[Snippet], CoverageStatus]


@dataclass
class RunResult:
    run_id: int
    all_scores: object  # Scores; avoid circular forward refs in dataclass
    covered_scores: object
    covered_snippet_paths: set[str]


def run(
    *,
    benchmark: TypeEvalPyBenchmark,
    translator: TranslationEngine,
    analyzer: AnalysisEngine,
    adapter: AnalysisResultAdapter,
    coverage_probe: CoverageProbe | None = None,
    stub_accuracy: float | None = None,
    seed: int | None = None,
    notes: str | None = None,
    db_path=None,
) -> RunResult:
    snippets = benchmark.load()
    coverage_probe = coverage_probe or (lambda _snippet: CoverageStatus.COVERED)

    per_snippet_scores: list[SnippetScores] = []
    covered_paths: set[str] = set()
    snippet_meta: list[tuple[Snippet, CoverageStatus, str | None]] = []

    for snip in snippets:
        status: CoverageStatus = CoverageStatus.COVERED
        error: str | None = None
        predictions: dict = {}

        try:
            translation = translator.translate(snip.source, snip.file_path)
            result = analyzer.analyze(translation)
            for ann in adapter.to_annotations(result, snip):
                predictions[ann.location] = ann.types
            status = coverage_probe(snip)
        except UnsupportedSourceError as e:
            status = CoverageStatus.UNSUPPORTED
            error = str(e) or None

        if status == CoverageStatus.COVERED or status == CoverageStatus.PARTIAL:
            covered_paths.add(snip.suite_path)

        gt = {a.location: a.types for a in snip.annotations}
        per_snippet_scores.append(
            score_snippet(
                suite_path=snip.suite_path,
                ground_truth=gt,
                predictions=predictions if status != CoverageStatus.UNSUPPORTED else {},
                location_to_record=_location_to_record,
            )
        )
        snippet_meta.append((snip, status, error))

    all_scores = _aggregate(per_snippet_scores)
    covered_only = [s for s in per_snippet_scores if s.suite_path in covered_paths]
    covered_scores = _aggregate(covered_only)

    from archway_benchmarks.store import DEFAULT_DB_PATH

    db_path = db_path or DEFAULT_DB_PATH
    with connect(db_path) as conn:
        run_id = create_run(
            conn,
            benchmark=benchmark.name,
            engine=f"{translator.name}+{analyzer.name}",
            stub_accuracy=stub_accuracy,
            seed=seed,
            notes=notes,
        )
        for snip, status, err in snippet_meta:
            record_snippet(
                conn,
                run_id,
                suite_path=snip.suite_path,
                source=snip.source,
                translation_status=status,
                error=err,
            )
        record_snippet_scores(conn, run_id, per_snippet_scores)
        record_scores(conn, run_id, scope="all", scores=all_scores)
        record_scores(conn, run_id, scope="covered", scores=covered_scores)

    return RunResult(
        run_id=run_id,
        all_scores=all_scores,
        covered_scores=covered_scores,
        covered_snippet_paths=covered_paths,
    )
