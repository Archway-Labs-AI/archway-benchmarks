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
import signal
import subprocess
import time
import uuid
from pathlib import Path

from archway_benchmarks.typybench_harness import (
    docker_image_name,
    local_docker_images,
    parse_result_csv,
    result_csv_path,
    score_command,
    stage_single_repo_prediction_root,
)
from archway_benchmarks.typybench_partitions import (
    HOLDOUT_VERSION,
    typybench_partition,
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
    include_incomplete: bool = False,
) -> list[str]:
    records = analysis_manifest.get("repositories", {})
    if not isinstance(records, dict):
        raise ValueError("analysis manifest repositories must be an object")
    accepted = {"complete"}
    if include_partial:
        accepted.add("partial")
    if include_incomplete:
        accepted.update({"partial", "timed_out", "failed"})
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


def _partitioned_aggregates(
    records: dict[str, object],
) -> dict[str, dict[str, object]]:
    return {
        "all": _aggregate_scores(records),
        "development": _aggregate_scores({
            name: record for name, record in records.items()
            if typybench_partition(name) == "development"
        }),
        "holdout": _aggregate_scores({
            name: record for name, record in records.items()
            if typybench_partition(name) == "holdout"
        }),
    }


def _update_aggregates(
    manifest: dict[str, object], records: dict[str, object]
) -> None:
    selection = manifest.get("selection", {})
    eligible = selection.get("eligible_repositories", list(records))
    selected_records = {name: records[name] for name in eligible if name in records}
    aggregates = _partitioned_aggregates(selected_records)
    manifest["coverage"] = {
        "eligible_repositories": len(eligible),
        "scored_repositories": aggregates["all"]["repositories_scored"],
        "unscored_repositories": {
            name: records.get(name, {}).get("status", "pending")
            for name in eligible
            if records.get(name, {}).get("status") != "complete"
            or not isinstance(records.get(name, {}).get("score"), dict)
        },
    }
    manifest["aggregate"] = aggregates["all"]
    manifest["aggregates"] = aggregates
    manifest["holdout_version"] = HOLDOUT_VERSION


def _run_command_group(command: list[str], *, timeout: int) -> int:
    """Run a scorer and terminate its Docker descendants on interruption.

    Upstream ``run.py`` launches Docker below a multiprocessing worker. Killing
    only the immediate Python process leaves the container orphaned, which can
    continue mutating the prediction tree after this runner has checkpointed a
    failure. A dedicated process group gives timeout and Ctrl-C one exact,
    bounded cleanup target.
    """

    process = subprocess.Popen(command, start_new_session=True)
    try:
        return process.wait(timeout=timeout)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        raise


class ContainerCleanupError(RuntimeError):
    """Stop the scoring pass when container termination is unconfirmed."""


def _run_podman_score(
    repo: str, image: str, predictions: Path, logs: Path, *, timeout: int,
) -> int:
    """Run unchanged scorer code in a pinned image with an exact cleanup target."""
    name = f"archway-score-{uuid.uuid4().hex}"
    source = (predictions / repo).resolve()
    if not source.is_dir() or not source.is_relative_to(predictions.resolve()):
        raise ValueError("scoring input must be a repository directory inside predictions")
    # Upstream reads its pickle cache independently of our resume flag. Never
    # let a nominal fresh execution silently adopt a previous scoring environment.
    if (source / f"{repo}_result_dict.pkl").exists():
        raise ValueError("fresh scoring requires a copied prediction tree without scorer caches")
    logs.mkdir(parents=True, exist_ok=True)
    command = [
        "podman", "run", "--rm", "--pull=never", "--name", name,
        "--userns=keep-id", "--user", f"{os.getuid()}:{os.getgid()}",
        "--network=none", "--cap-drop=all", "--security-opt=no-new-privileges",
        "--memory=8g", "--pids-limit=256", "--timeout", str(timeout),
        "--env", "PYTHONPYCACHEPREFIX=/tmp/python-cache",
        "--env", "MYPY_CACHE_DIR=/tmp/mypy-cache",
        "--mount", f"type=bind,source={source},target=/mnt/{repo}",
        "--entrypoint", "python", image,
        "/typybench/scripts/evaluation.py", "-n", repo,
        "-d", "/typybenchdata", "-p", "/mnt",
    ]
    _write_json(logs / f"{repo}-command.json", {"command": command})
    with (logs / f"{repo}.log").open("w") as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
        try:
            return process.wait(timeout=timeout + 15)
        finally:
            # Killing the client alone does not establish container termination.
            try:
                cleanup = subprocess.run(
                    ["podman", "rm", "--force", "--ignore", name],
                    capture_output=True, text=True, timeout=30,
                )
                _write_json(logs / f"{repo}-cleanup.json", {
                    "container": name, "returncode": cleanup.returncode,
                    "stdout": cleanup.stdout, "stderr": cleanup.stderr,
                })
                if cleanup.returncode:
                    raise ContainerCleanupError(f"container cleanup failed: {name}")
            except subprocess.TimeoutExpired as error:
                _write_json(logs / f"{repo}-cleanup.json", {
                    "container": name, "status": "timed_out",
                })
                raise ContainerCleanupError(f"container cleanup timed out: {name}") from error
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("typybench_root", type=Path)
    parser.add_argument("--repo", action="append", dest="repos")
    parser.add_argument("--timeout-per-repo", type=int, default=900)
    parser.add_argument("--include-partial", action="store_true")
    parser.add_argument(
        "--include-incomplete", action="store_true",
        help="score retained outputs from all terminal attempts, including unannotated failure fallbacks",
    )
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--podman-image-map", type=Path,
        help="JSON mapping repository names to immutable local image IDs; use rootless Podman",
    )
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
        include_incomplete=args.include_incomplete,
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

    manifest["selection"] = {
        "include_partial": args.include_partial,
        "include_incomplete": args.include_incomplete,
        "eligible_repositories": repositories,
        "excluded_repositories": {
            name: record.get("status")
            for name, record in analysis_manifest["repositories"].items()
            if name not in repositories
        },
    }
    manifest["analysis_outcomes"] = {
        name: {key: record.get(key) for key in (
            "status", "files_total", "files_analyzed", "files_failed", "failure_count",
        )}
        for name, record in analysis_manifest["repositories"].items()
    }
    score_records = manifest.setdefault("repositories", {})
    assert isinstance(score_records, dict)
    podman_images = None
    if args.podman_image_map is not None:
        podman_images = json.loads(args.podman_image_map.read_text())
        if not isinstance(podman_images, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            or len(value.removeprefix("sha256:")) != 64
            or any(char not in "0123456789abcdef" for char in value.removeprefix("sha256:"))
            for key, value in podman_images.items()
        ):
            parser.error("Podman image map must contain repository names and full image IDs")
        runtime = json.loads(subprocess.check_output(["podman", "info", "--format", "json"], text=True))
        if runtime["host"]["security"]["rootless"] is not True:
            raise RuntimeError("Podman scoring requires a rootless runtime")
        runtime_record = {
            "kind": "podman", "rootless": True,
            "version": runtime["version"]["Version"], "images": podman_images,
            "memory": "8g", "pids_limit": 256, "network": "none",
        }
        if not args.no_resume and score_records and manifest.get("runtime") != runtime_record:
            raise RuntimeError("cannot resume scores under a different runtime or image map")
        manifest["runtime"] = runtime_record
    local_images = local_docker_images() if podman_images is None else set()
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
            _update_aggregates(manifest, score_records)
            _write_json(score_manifest_path, manifest)
            print(
                f"ARCHWAY_TYPYBENCH_SCORE adopt {index}/{len(repositories)} {repo_name}",
                flush=True,
            )
            continue
        if (repo_name not in podman_images if podman_images is not None
                else docker_image_name(repo_name) not in local_images):
            score_records[repo_name] = {
                "status": "unavailable",
                "reason": "image_missing",
                "docker_image": docker_image_name(repo_name),
            }
            manifest["updated_unix"] = time.time()
            _update_aggregates(manifest, score_records)
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
            if podman_images is not None:
                return_code = _run_podman_score(
                    repo_name, podman_images[repo_name], predictions_root,
                    log_root, timeout=args.timeout_per_repo,
                )
            else:
                return_code = _run_command_group(
                score_command(
                    typybench_root=args.typybench_root,
                    data_path=args.data_root,
                    pred_path=repo_staging_root,
                    repo=repo_name,
                    progress_jsonl=progress_path,
                    log_dir=log_root,
                ),
                timeout=args.timeout_per_repo,
                )
            if return_code != 0:
                raise RuntimeError(f"official scorer exited {return_code}")
            score = _score_values(csv_path)
            record = {
                "status": "complete",
                "elapsed_seconds": time.monotonic() - started,
                "score": score,
            }
        except ContainerCleanupError as exc:
            score_records[repo_name] = {
                "status": "failed", "error": str(exc),
                "finished_unix": time.time(),
            }
            manifest["run_status"] = "cleanup_failed"
            _update_aggregates(manifest, score_records)
            _write_json(score_manifest_path, manifest)
            raise
        except Exception as exc:
            record = {
                "status": "failed",
                "elapsed_seconds": time.monotonic() - started,
                "error": f"{type(exc).__name__}: {exc}",
            }
        record["finished_unix"] = time.time()
        score_records[repo_name] = record
        manifest["updated_unix"] = time.time()
        _update_aggregates(manifest, score_records)
        _write_json(score_manifest_path, manifest)
        print(
            f"ARCHWAY_TYPYBENCH_SCORE {record['status']} {repo_name} "
            f"{record['elapsed_seconds']:.3f}s",
            flush=True,
        )

    manifest["updated_unix"] = time.time()
    _update_aggregates(manifest, score_records)
    manifest["run_status"] = (
        "no_eligible_repositories" if not repositories
        else "finished_with_incomplete_repositories"
        if manifest["coverage"]["unscored_repositories"] else "complete"
    )
    _write_json(score_manifest_path, manifest)


if __name__ == "__main__":
    main()
