"""Checkpointable multi-repository TypyBench successor emission.

Each repository is analyzed in one isolated persistent reduced-product session.
The manifest is replaced atomically after every state transition, so an
interrupted framework-scale run resumes without replaying completed repos.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from archway_benchmarks.typybench_archway_emit import emit_archway_predictions
from archway_benchmarks.typybench_harness import (
    available_repos,
    untyped_source_root,
)
from archway_benchmarks.typybench_partitions import typybench_partition


def _python_file_count(root: Path) -> int:
    return sum(1 for _path in root.rglob("*.py"))


def _git_revision(worktree: Path) -> str:
    """Resolve the immutable revision used by one checkpointed run."""

    completed = subprocess.run(
        ("git", "-C", str(worktree.resolve()), "rev-parse", "HEAD"),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _stats_record(stats, elapsed: float) -> dict[str, object]:
    summary = next(
        (
            profile.analysis_summary
            for profile in stats.file_profiles
            if profile.analysis_summary is not None
        ),
        None,
    )
    probe_failure = next((
        failure for failure in stats.failures
        if str(failure.get("error", "")).startswith((
            "TimeoutExpired:", "engine probe failed:",
        ))
    ), None)
    return {
        "status": (
            "failed" if probe_failure is not None
            else "complete" if not stats.failures else "partial"
        ),
        "elapsed_seconds": elapsed,
        "files_total": stats.files_total,
        "files_analyzed": stats.files_analyzed,
        "files_failed": stats.files_failed,
        "functions_seen": stats.functions_seen,
        "functions_annotated": stats.functions_annotated,
        "params_annotated": stats.params_annotated,
        "returns_annotated": stats.returns_annotated,
        "variables_annotated": stats.variables_annotated,
        "failure_count": len(stats.failures),
        "failures": list(stats.failures[:20]),
        "analysis_summary": summary,
    }


def _terminal_run_status(
    records: dict[str, object], repos: list[str]
) -> str:
    """Describe a fully attempted corpus without hiding incomplete repos."""

    statuses = {
        name: (
            records.get(name, {}).get("status")
            if isinstance(records.get(name), dict) else None
        )
        for name in repos
    }
    if all(status == "complete" for status in statuses.values()):
        return "complete"
    if any(status == "running" for status in statuses.values()):
        return "interrupted"
    return "finished_with_incomplete_repositories"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("engine_worktree", type=Path)
    parser.add_argument("--repo", action="append", dest="repos")
    parser.add_argument(
        "--partition",
        choices=("all", "development", "holdout"),
        default="all",
        help="run the frozen development or holdout partition",
    )
    parser.add_argument("--timeout-per-repo", type=int, default=900)
    parser.add_argument("--max-total-seconds", type=int, default=14_400)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    if args.timeout_per_repo <= 0:
        parser.error("--timeout-per-repo must be positive")
    if args.max_total_seconds <= 0:
        parser.error("--max-total-seconds must be positive")

    available = {
        name for name in available_repos(args.data_root)
        if _python_file_count(untyped_source_root(name, args.data_root)) > 0
    }
    partition_available = {
        name for name in available
        if args.partition == "all"
        or typybench_partition(name) == args.partition
    }
    selected = set(args.repos or partition_available)
    unknown = sorted(selected - available)
    if unknown:
        parser.error("unknown repositories: " + ", ".join(unknown))
    wrong_partition = sorted(selected - partition_available)
    if args.partition != "all" and wrong_partition:
        parser.error(
            f"repositories outside {args.partition} partition: "
            + ", ".join(wrong_partition)
        )

    repos = sorted(
        selected,
        key=lambda name: (
            _python_file_count(untyped_source_root(name, args.data_root)),
            name,
        ),
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    predictions_root = args.output_root / "predictions"
    manifest_path = args.output_root / "manifest.json"
    engine_revision = _git_revision(args.engine_worktree)
    harness_revision = _git_revision(Path(__file__).resolve().parents[1])
    if manifest_path.exists() and not args.no_resume:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_revisions = {
            "engine_revision": engine_revision,
            "harness_revision": harness_revision,
            "partition": args.partition,
            "selected_repositories": repos,
        }
        mismatches = {
            name: (manifest.get(name), expected)
            for name, expected in expected_revisions.items()
            if manifest.get(name) != expected
        }
        if mismatches:
            raise RuntimeError(
                "refusing to resume TypyBench across revisions: "
                + ", ".join(
                    f"{name}={actual!r} (current {expected!r})"
                    for name, (actual, expected) in mismatches.items()
                )
            )
    else:
        manifest = {
            "schema": "archway.typybench.successor-run.v1",
            "created_unix": time.time(),
            "data_root": str(args.data_root.resolve()),
            "engine_worktree": str(args.engine_worktree.resolve()),
            "engine_revision": engine_revision,
            "harness_revision": harness_revision,
            "predictions_root": str(predictions_root.resolve()),
            "partition": args.partition,
            # Freeze the ordered workload itself.  Repository availability can
            # change between checkpoint attempts; revision pins alone cannot
            # prove that a resumed aggregate represents the same run.
            "selected_repositories": repos,
            "repositories": {},
        }

    records = manifest.setdefault("repositories", {})
    assert isinstance(records, dict)
    manifest["run_status"] = "running"
    manifest["run_started_unix"] = time.time()
    manifest["run_attempt"] = int(manifest.get("run_attempt", 0)) + 1
    manifest["updated_unix"] = time.time()
    _write_manifest(manifest_path, manifest)
    run_started = time.monotonic()
    for index, repo_name in enumerate(repos, 1):
        existing = records.get(repo_name)
        if (
            not args.no_resume
            and isinstance(existing, dict)
            # A partial repository retains useful checkpointed predictions,
            # but it has not satisfied the full-run contract.  Resume must
            # retry it in the same persistent per-repository session rather
            # than silently treating missing roots as complete.
            and existing.get("status") == "complete"
            and (predictions_root / repo_name).is_dir()
        ):
            print(f"ARCHWAY_TYPYBENCH skip {index}/{len(repos)} {repo_name}", flush=True)
            continue

        remaining_total = args.max_total_seconds - (
            time.monotonic() - run_started
        )
        if remaining_total <= 0:
            manifest["run_status"] = "time_budget_exhausted"
            manifest["run_elapsed_seconds"] = (
                time.monotonic() - run_started
            )
            manifest["updated_unix"] = time.time()
            _write_manifest(manifest_path, manifest)
            break

        source_root = untyped_source_root(repo_name, args.data_root)
        records[repo_name] = {
            "status": "running",
            "started_unix": time.time(),
            "python_files": _python_file_count(source_root),
        }
        _write_manifest(manifest_path, manifest)
        print(f"ARCHWAY_TYPYBENCH start {index}/{len(repos)} {repo_name}", flush=True)
        started = time.monotonic()
        try:
            stats = emit_archway_predictions(
                repo_name=repo_name,
                untyped_root=source_root,
                predictions_root=predictions_root,
                engine_worktree=args.engine_worktree,
                timeout=max(
                    1, min(args.timeout_per_repo, int(remaining_total))
                ),
                checkpoint_roots=True,
                # Declarative class transforms (dataclasses, PEP-681-style
                # model bases) expose constructor types through diagram-owned
                # ClassFieldTypeOf facts.  Emitting only that semantic family
                # restores the source surface needed by the official scorer
                # without annotating arbitrary class attributes.
                emit_class_field_annotations=True,
            )
            record = _stats_record(stats, time.monotonic() - started)
        except Exception as exc:
            record = {
                "status": "failed",
                "elapsed_seconds": time.monotonic() - started,
                "error": f"{type(exc).__name__}: {exc}",
            }
        record["finished_unix"] = time.time()
        records[repo_name] = record
        manifest["updated_unix"] = time.time()
        _write_manifest(manifest_path, manifest)
        print(
            f"ARCHWAY_TYPYBENCH {record['status']} {repo_name} "
            f"{record['elapsed_seconds']:.3f}s",
            flush=True,
        )
    else:
        manifest["run_status"] = _terminal_run_status(records, repos)
        manifest["run_elapsed_seconds"] = time.monotonic() - run_started
        manifest["updated_unix"] = time.time()
        _write_manifest(manifest_path, manifest)


if __name__ == "__main__":
    main()
