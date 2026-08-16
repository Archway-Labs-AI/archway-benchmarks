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
import subprocess
import sys
import time

from archway_benchmarks.benchmarks import TypeEvalPyAutogenBenchmark
from archway_benchmarks.engines.archway import ArchwayTranslationEngine
from archway_benchmarks.engines.successor_archway import (
    SuccessorArchwayAnalysisEngine,
    SuccessorTypeEvalPyAdapter,
)


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus_root", type=Path)
    parser.add_argument("checkpoint_jsonl", type=Path)
    parser.add_argument("engine_worktree", type=Path)
    parser.add_argument("--per-snippet-timeout", type=float, default=30.0)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--max-snippets", type=int)
    parser.add_argument("--no-resume", action="store_true")
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
    summary_path = args.checkpoint_jsonl.with_suffix(".summary.json")
    temporary = summary_path.with_suffix(summary_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, summary_path)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
