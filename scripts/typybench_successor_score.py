"""Checkpoint and score completed successor TypyBench predictions.

Scoring is deliberately a separate resumable pass from analysis.  TypyBench's
official scorer runs one Docker container per repository and can therefore be
repeated without reopening the persistent Archway analysis session or changing
its timing evidence.  A separate score manifest also avoids lost updates while
the analysis runner is still checkpointing repositories.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from archway_benchmarks.typybench_harness import (
    docker_image_name,
    local_docker_images,
    parse_result_csv,
    result_csv_path,
    score_command,
    stage_single_repo_prediction_root,
)


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _score_values(csv_path: Path) -> dict[str, object]:
    result = parse_result_csv(csv_path)
    return {
        "repo_name": result.repo_name,
        "total_vars": result.total_vars,
        **result.values,
        "csv_path": str(result.csv_path.resolve()),
    }


def _result_is_current(csv_path: Path, prediction_root: Path) -> bool:
    """Return whether an existing official score postdates its source tree."""

    if not csv_path.is_file():
        return False
    scored_at = csv_path.stat().st_mtime_ns
    return all(
        path.stat().st_mtime_ns <= scored_at
        for path in prediction_root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".pyi"}
    )


def _eligible_repositories(
    analysis_manifest: dict[str, object],
    *,
    selected: set[str] | None,
    include_partial: bool,
) -> list[str]:
    records = analysis_manifest.get("repositories", {})
    if not isinstance(records, dict):
        raise ValueError("analysis manifest repositories must be an object")
    accepted = {"complete"}
    if include_partial:
        accepted.add("partial")
    return sorted(
        name
        for name, record in records.items()
        if isinstance(name, str)
        and isinstance(record, dict)
        and record.get("status") in accepted
        and (selected is None or name in selected)
    )


def _aggregate_scores(records: dict[str, object]) -> dict[str, object]:
    """Compute observation-weighted gates over completed official scores."""

    scores = [
        record["score"]
        for record in records.values()
        if isinstance(record, dict)
        and record.get("status") == "complete"
        and isinstance(record.get("score"), dict)
    ]
    total = sum(int(score["total_vars"]) for score in scores)

    def weighted(field: str) -> float | None:
        terms = [
            (int(score["total_vars"]), score.get(field))
            for score in scores
            if score.get(field) is not None
        ]
        denominator = sum(count for count, _value in terms)
        if not denominator:
            return None
        return sum(count * float(value) for count, value in terms) / denominator

    return {
        "repositories_scored": len(scores),
        "total_vars": total,
        "overall_score_exact": weighted("overall_score_exact"),
        "overall_score": weighted("overall_score"),
        "missing_ratio": weighted("missing_ratio"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("typybench_root", type=Path)
    parser.add_argument("--repo", action="append", dest="repos")
    parser.add_argument("--timeout-per-repo", type=int, default=900)
    parser.add_argument("--include-partial", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    if args.timeout_per_repo <= 0:
        parser.error("--timeout-per-repo must be positive")

    analysis_manifest_path = args.run_root / "manifest.json"
    score_manifest_path = args.run_root / "score-manifest.json"
    predictions_root = args.run_root / "predictions"
    analysis_manifest = json.loads(
        analysis_manifest_path.read_text(encoding="utf-8")
    )
    repositories = _eligible_repositories(
        analysis_manifest,
        selected=set(args.repos) if args.repos else None,
        include_partial=args.include_partial,
    )

    if score_manifest_path.exists() and not args.no_resume:
        manifest = json.loads(score_manifest_path.read_text(encoding="utf-8"))
        if manifest.get("predictions_root") != str(predictions_root.resolve()):
            raise RuntimeError("score manifest belongs to a different prediction root")
    else:
        manifest = {
            "schema": "archway.typybench.successor-scores.v1",
            "created_unix": time.time(),
            "analysis_manifest": str(analysis_manifest_path.resolve()),
            "predictions_root": str(predictions_root.resolve()),
            "repositories": {},
        }

    score_records = manifest.setdefault("repositories", {})
    assert isinstance(score_records, dict)
    local_images = local_docker_images()
    staging_root = args.run_root / ".scoring-stage"
    progress_path = args.run_root / "scoring-progress.jsonl"
    log_root = args.run_root / "scoring-logs"

    for index, repo_name in enumerate(repositories, 1):
        existing = score_records.get(repo_name)
        csv_path = result_csv_path(repo_name, predictions_root)
        if (
            not args.no_resume
            and isinstance(existing, dict)
            and existing.get("status") == "complete"
            and csv_path.is_file()
        ):
            print(f"ARCHWAY_TYPYBENCH_SCORE skip {index}/{len(repositories)} {repo_name}", flush=True)
            continue
        if (
            not args.no_resume
            and _result_is_current(csv_path, predictions_root / repo_name)
        ):
            score_records[repo_name] = {
                "status": "complete",
                "elapsed_seconds": 0.0,
                "adopted_existing_result": True,
                "score": _score_values(csv_path),
                "finished_unix": time.time(),
            }
            manifest["updated_unix"] = time.time()
            manifest["aggregate"] = _aggregate_scores(score_records)
            _write_json(score_manifest_path, manifest)
            print(
                f"ARCHWAY_TYPYBENCH_SCORE adopt {index}/{len(repositories)} {repo_name}",
                flush=True,
            )
            continue
        if docker_image_name(repo_name) not in local_images:
            score_records[repo_name] = {
                "status": "unavailable",
                "reason": "docker_image_missing",
                "docker_image": docker_image_name(repo_name),
            }
            manifest["updated_unix"] = time.time()
            manifest["aggregate"] = _aggregate_scores(score_records)
            _write_json(score_manifest_path, manifest)
            continue

        # Give every repository an isolated one-repo view.  Besides making the
        # upstream scorer's broad pred-path scan bounded, this prevents a
        # resumed/manual scorer from retargeting another active scorer's
        # staging symlink.
        repo_staging_root = staging_root / repo_name
        stage_single_repo_prediction_root(
            repo_name=repo_name,
            predictions_root=predictions_root,
            staging_root=repo_staging_root,
        )
        started = time.monotonic()
        score_records[repo_name] = {
            "status": "running",
            "started_unix": time.time(),
        }
        _write_json(score_manifest_path, manifest)
        print(f"ARCHWAY_TYPYBENCH_SCORE start {index}/{len(repositories)} {repo_name}", flush=True)
        try:
            completed = subprocess.run(
                score_command(
                    typybench_root=args.typybench_root,
                    data_path=args.data_root,
                    pred_path=repo_staging_root,
                    repo=repo_name,
                    progress_jsonl=progress_path,
                    log_dir=log_root,
                ),
                check=False,
                timeout=args.timeout_per_repo,
            )
            if completed.returncode != 0:
                raise RuntimeError(f"official scorer exited {completed.returncode}")
            score = _score_values(csv_path)
            record = {
                "status": "complete",
                "elapsed_seconds": time.monotonic() - started,
                "score": score,
            }
        except Exception as exc:
            record = {
                "status": "failed",
                "elapsed_seconds": time.monotonic() - started,
                "error": f"{type(exc).__name__}: {exc}",
            }
        record["finished_unix"] = time.time()
        score_records[repo_name] = record
        manifest["updated_unix"] = time.time()
        manifest["aggregate"] = _aggregate_scores(score_records)
        _write_json(score_manifest_path, manifest)
        print(
            f"ARCHWAY_TYPYBENCH_SCORE {record['status']} {repo_name} "
            f"{record['elapsed_seconds']:.3f}s",
            flush=True,
        )

    manifest["run_status"] = "complete"
    manifest["updated_unix"] = time.time()
    manifest["aggregate"] = _aggregate_scores(score_records)
    _write_json(score_manifest_path, manifest)


if __name__ == "__main__":
    main()
