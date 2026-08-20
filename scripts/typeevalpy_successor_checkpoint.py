"""Checkpointed diagram-successor TypeEvalPy runner.

One JSONL record is appended after every snippet.  A resumed run reuses only
records produced by the same corpus, engine revision, and harness revision;
the first analysis error or per-snippet timeout stops the run for immediate
investigation instead of silently consuming the rest of a large corpus.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time

from archway_benchmarks.benchmarks import TypeEvalPyAutogenBenchmark
from archway_benchmarks.engines.archway import ArchwayTranslationEngine
from archway_benchmarks.engines.successor_archway import (
    SuccessorArchwayAnalysisEngine,
    SuccessorTypeEvalPyAdapter,
)
from archway_benchmarks.coverage import CoverageStatus
from archway_benchmarks.scoring.typeevalpy import _aggregate, score_snippet
from archway_benchmarks.store import (
    connect as connect_store,
    create_run,
    record_scores,
    record_snippet,
    record_snippet_scores,
)
from archway_benchmarks.benchmarks.typeevalpy import _location_to_record
from archway_benchmarks.types import Location


def _revision(path: Path) -> str:
    return subprocess.run(
        ("git", "-C", str(path), "rev-parse", "HEAD"),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _load_records(path: Path) -> tuple[dict[str, object] | None, dict[str, dict]]:
    if not path.exists():
        return None, {}
    header = None
    records = {}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                # Only a process interruption can leave an incomplete final
                # append. Earlier corruption is not a resumable checkpoint.
                if stream.read():
                    raise RuntimeError(
                        f"invalid checkpoint JSON at line {line_number}"
                    )
                break
            if item.get("kind") == "header":
                header = item
            elif item.get("kind") == "snippet":
                records[item["suite_path"]] = item
    return header, records


def _summary(records: dict[str, dict], total_snippets: int) -> dict[str, object]:
    classifications: Counter[str] = Counter()
    for record in records.values():
        classifications.update(record.get("classifications", {}))
    annotations = sum(item["annotations"] for item in records.values())
    exact = sum(item["exact"] for item in records.values())
    return {
        "snippets_complete": len(records),
        "snippets_total": total_snippets,
        "annotations": annotations,
        "predictions": sum(item["predictions"] for item in records.values()),
        "exact": exact,
        "exact_fraction": exact / annotations if annotations else 0.0,
        "elapsed_seconds": sum(item["seconds"] for item in records.values()),
        "classifications": dict(sorted(classifications.items())),
    }


def _prediction_record(annotation) -> dict[str, object]:
    location = annotation.location
    return {
        "file": location.file,
        "line": location.line,
        "col": location.col,
        "kind": location.kind,
        "name": location.name,
        "function": location.function,
        "types": sorted(annotation.types),
    }


def _prediction_map(record: dict) -> dict[Location, frozenset[str]]:
    return {
        Location(
            file=str(item["file"]),
            line=int(item["line"]),
            col=(int(item["col"]) if item.get("col") is not None else None),
            kind=str(item["kind"]),
            name=str(item["name"]),
            function=(
                str(item["function"])
                if item.get("function") is not None else None
            ),
        ): frozenset(str(value) for value in item["types"])
        for item in record.get("prediction_records", ())
    }


def _persist_run(
    *,
    benchmark,
    snippets,
    records: dict[str, dict],
    db_path: Path,
    notes: str | None,
    metadata: dict[str, object],
) -> int:
    per_snippet = []
    for snippet in snippets:
        predictions = _prediction_map(records[snippet.suite_path])
        per_snippet.append(score_snippet(
            suite_path=snippet.suite_path,
            ground_truth={
                item.location: item.types for item in snippet.annotations
            },
            predictions=predictions,
            location_to_record=_location_to_record,
        ))
    scores = _aggregate(per_snippet)
    with connect_store(db_path) as connection:
        run_id = create_run(
            connection,
            benchmark=benchmark.name,
            engine="archway-translation+archway-successor-analysis",
            stub_accuracy=None,
            seed=None,
            notes=notes,
            metadata=metadata,
        )
        for snippet in snippets:
            record_snippet(
                connection,
                run_id,
                suite_path=snippet.suite_path,
                source=snippet.source,
                translation_status=CoverageStatus.COVERED,
            )
        record_snippet_scores(connection, run_id, per_snippet)
        record_scores(connection, run_id, scope="all", scores=scores)
        record_scores(connection, run_id, scope="covered", scores=scores)
    return run_id


def _completed_run_id(summary_path: Path, db_path: Path) -> int | None:
    if not summary_path.is_file() or not db_path.is_file():
        return None
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if Path(str(summary.get("db_path", ""))) != db_path:
        return None
    run_id = summary.get("local_run_id")
    if not isinstance(run_id, int):
        return None
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "select 1 from runs where id=?", (run_id,)
        ).fetchone()
    finally:
        connection.close()
    return run_id if row is not None else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus_root", type=Path)
    parser.add_argument("checkpoint_jsonl", type=Path)
    parser.add_argument("engine_worktree", type=Path)
    parser.add_argument("--per-snippet-timeout", type=float, default=30.0)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--max-snippets", type=int)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--notes")
    args = parser.parse_args()
    if args.per_snippet_timeout <= 0:
        parser.error("--per-snippet-timeout must be positive")
    if args.progress_every <= 0:
        parser.error("--progress-every must be positive")

    engine_worktree = args.engine_worktree.resolve()
    sys.path.insert(0, str(engine_worktree))
    import sd_core

    loaded_roots = tuple(Path(item).resolve() for item in sd_core.__path__)
    if not any(path.is_relative_to(engine_worktree) for path in loaded_roots):
        raise RuntimeError("sd_core did not load from the requested worktree")

    benchmark = TypeEvalPyAutogenBenchmark(args.corpus_root.resolve())
    snippets = benchmark.load()
    if args.max_snippets is not None:
        snippets = snippets[:args.max_snippets]
    harness_root = Path(__file__).resolve().parents[1]
    expected_header = {
        "kind": "header",
        "schema_version": 2,
        "corpus_root": str(args.corpus_root.resolve()),
        "engine_revision": _revision(engine_worktree),
        "harness_revision": _revision(harness_root),
        "corpus_revision": _revision(args.corpus_root.resolve()),
        "snippet_count": len(snippets),
    }
    header, records = (
        (None, {}) if args.no_resume
        else _load_records(args.checkpoint_jsonl)
    )
    if header is not None and header != expected_header:
        raise RuntimeError(
            "checkpoint provenance differs from this run; use a new path"
        )
    summary_path = args.checkpoint_jsonl.with_suffix(".summary.json")
    if (
        not args.no_resume
        and args.db is not None
        and len(records) == len(snippets)
        and _completed_run_id(summary_path, args.db.resolve()) is not None
    ):
        print(summary_path.read_text(encoding="utf-8").strip())
        return
    args.checkpoint_jsonl.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if header is None or args.no_resume else "a"
    translator = ArchwayTranslationEngine(
        corpus_root=benchmark.corpus_root,
        dependency_roots=tuple(benchmark.dependency_roots),
    )
    analyzer = SuccessorArchwayAnalysisEngine(record_events=False)
    adapter = SuccessorTypeEvalPyAdapter()

    with args.checkpoint_jsonl.open(mode, encoding="utf-8") as stream:
        if mode == "w":
            stream.write(json.dumps(expected_header, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        for index, snippet in enumerate(snippets, 1):
            if snippet.suite_path in records:
                continue
            started = time.monotonic()

            def timeout_snippet(_signum, _frame):
                raise TimeoutError(
                    f"snippet exceeded {args.per_snippet_timeout:g}s"
                )

            previous_handler = signal.signal(signal.SIGALRM, timeout_snippet)
            signal.setitimer(signal.ITIMER_REAL, args.per_snippet_timeout)
            result = None
            predictions = []
            escaped_error = None
            try:
                result = analyzer.analyze(
                    translator.translate(snippet.source, snippet.file_path)
                )
                predictions = adapter.to_annotations(result, snippet)
            except Exception as exc:
                escaped_error = f"{type(exc).__name__}: {exc}"
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous_handler)
            elapsed = time.monotonic() - started
            error = (
                escaped_error
                if escaped_error is not None
                else result.error
                if result is not None
                else "analysis returned no result"
            )
            predicted = {
                annotation.location: annotation.types
                for annotation in predictions
            }
            ground_truth = {
                annotation.location: annotation.types
                for annotation in snippet.annotations
            }
            classifications = Counter(
                gap.classification
                for gap in (result.gaps if result is not None else ())
            )
            record = {
                "kind": "snippet",
                "suite_path": snippet.suite_path,
                "seconds": elapsed,
                "annotations": len(ground_truth),
                "predictions": len(predicted),
                "exact": sum(
                    predicted.get(location) == expected
                    for location, expected in ground_truth.items()
                ),
                "classifications": dict(sorted(classifications.items())),
                "error": error,
                "forward_productions": (
                    result.session.scheduler.production_execution_count
                    if result is not None and result.session is not None else 0
                ),
                "targeted_waves": (
                    len(result.targeted_runs) if result is not None else 0
                ),
                "prediction_records": [
                    _prediction_record(item) for item in predictions
                ],
            }
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
            records[snippet.suite_path] = record
            if (
                index % args.progress_every == 0
                or elapsed >= min(5.0, args.per_snippet_timeout / 2)
                or error
                or index == len(snippets)
            ):
                os.fsync(stream.fileno())
                current = _summary(records, len(snippets))
                print(
                    "TYPEEVALPY_PROGRESS "
                    + json.dumps({
                        "index": index,
                        "suite_path": snippet.suite_path,
                        "snippet_seconds": elapsed,
                        **current,
                    }, sort_keys=True),
                    file=sys.stderr,
                    flush=True,
                )
            if error:
                raise RuntimeError(
                    f"analysis failed at {snippet.suite_path}: {error}"
                )
        os.fsync(stream.fileno())

    summary = _summary(records, len(snippets))
    if args.db is not None:
        resolved_db = args.db.resolve()
        summary["local_run_id"] = _persist_run(
            benchmark=benchmark,
            snippets=snippets,
            records=records,
            db_path=resolved_db,
            notes=args.notes,
            metadata={
                "analysis_surface": "diagram-only",
                "record_events": False,
                "session_policy": "persistent-forward-then-targeted",
                "checkpoint_jsonl": str(args.checkpoint_jsonl.resolve()),
                **expected_header,
            },
        )
        summary["db_path"] = str(resolved_db)
    temporary = summary_path.with_suffix(summary_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, summary_path)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
