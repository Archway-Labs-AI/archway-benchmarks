import importlib.util
import os
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace

import pytest


_SCRIPT = Path(__file__).parents[1] / "scripts" / "typybench_successor_score.py"
_SPEC = importlib.util.spec_from_file_location("typybench_successor_score", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


@pytest.mark.parametrize("cleanup_status", [0, 1, "timeout"])
def test_podman_timeout_removes_exact_container_and_kills_remaining_client(tmp_path, monkeypatch, cleanup_status):
    predictions = tmp_path / "predictions"
    (predictions / "repo").mkdir(parents=True)
    calls = []

    class Process:
        killed = False

        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("podman", timeout)
            return -9

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    process = Process()
    monkeypatch.setattr(_MODULE.subprocess, "Popen", lambda command, **kwargs: (calls.append(command), process)[1])
    def cleanup(command, **kwargs):
        calls.append(command)
        if cleanup_status == "timeout":
            raise subprocess.TimeoutExpired(command, 30)
        return SimpleNamespace(returncode=cleanup_status, stdout="", stderr="")

    monkeypatch.setattr(_MODULE.subprocess, "run", cleanup)
    expected = subprocess.TimeoutExpired if cleanup_status == 0 else _MODULE.ContainerCleanupError
    with pytest.raises(expected):
        _MODULE._run_podman_score("repo", "a" * 64, predictions, tmp_path / "logs", timeout=1)
    assert process.killed
    run, cleanup = calls
    assert cleanup == ["podman", "rm", "--force", "--ignore", run[run.index("--name") + 1]]
    assert "--userns=keep-id" in run and "--network=none" in run
    assert "type=bind,source=" + str(predictions / "repo") + ",target=/mnt/repo" in run


def test_podman_refuses_previous_scorer_cache(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "repo_result_dict.pkl").write_bytes(b"old environment")
    with pytest.raises(ValueError, match="without scorer caches"):
        _MODULE._run_podman_score("repo", "a" * 64, tmp_path, tmp_path / "logs", timeout=1)


def test_eligible_repositories_defaults_to_complete_and_supports_selection() -> None:
    manifest = {
        "repositories": {
            "paper-qa": {"status": "complete"},
            "flake8": {"status": "partial"},
            "black": {"status": "failed"},
            "rich": {"status": "running"},
        }
    }

    assert _MODULE._eligible_repositories(
        manifest, selected=None, include_partial=False
    ) == ["paper-qa"]
    assert _MODULE._eligible_repositories(
        manifest,
        selected={"flake8", "paper-qa"},
        include_partial=True,
    ) == ["flake8", "paper-qa"]


def test_score_values_preserves_official_exact_weighted_and_missing(tmp_path) -> None:
    columns = _MODULE.parse_result_csv.__globals__["REQUIRED_RESULT_COLUMNS"]
    values = {column: "0.5" for column in columns}
    values.update({
        "repo_name": "paper-qa",
        "total_vars": "100",
        "overall_score": "0.35",
        "overall_score_exact": "0.30",
        "missing_ratio": "0.10",
        "repo_a_consistency": "0",
        "repo_b_consistency": "0",
    })
    path = tmp_path / "paper-qa_results_w_exact.csv"
    path.write_text(
        ",".join(columns) + "\n" + ",".join(values[column] for column in columns) + "\n",
        encoding="utf-8",
    )

    score = _MODULE._score_values(path)

    assert score["repo_name"] == "paper-qa"
    assert score["total_vars"] == 100
    assert score["overall_score"] == 0.35
    assert score["overall_score_exact"] == 0.30
    assert score["missing_ratio"] == 0.10


def test_existing_result_is_current_only_when_it_postdates_predictions(tmp_path) -> None:
    prediction = tmp_path / "repo" / "module.py"
    prediction.parent.mkdir()
    prediction.write_text("value = 1\n", encoding="utf-8")
    result = prediction.parent / "repo_results_w_exact.csv"
    result.write_text("score\n", encoding="utf-8")

    assert _MODULE._result_is_current(result, prediction.parent)

    newer = result.stat().st_mtime_ns + 1_000_000_000
    os.utime(prediction, ns=(newer, newer))
    assert not _MODULE._result_is_current(result, prediction.parent)


def test_aggregate_scores_weights_repositories_by_observations() -> None:
    aggregate = _MODULE._aggregate_scores({
        "small": {
            "status": "complete",
            "score": {
                "total_vars": 10,
                "overall_score_exact": 0.8,
                "overall_score": 0.9,
                "missing_ratio": 0.1,
            },
        },
        "large": {
            "status": "complete",
            "score": {
                "total_vars": 90,
                "overall_score_exact": 0.2,
                "overall_score": 0.3,
                "missing_ratio": 0.4,
            },
        },
        "failed": {"status": "failed"},
    })

    assert aggregate == {
        "repositories_scored": 2,
        "total_vars": 100,
        "overall_score_exact": 0.26,
        "overall_score": pytest.approx(0.36),
        "missing_ratio": pytest.approx(0.37),
    }


def test_partitioned_aggregates_keep_holdout_evidence_separate() -> None:
    records = {
        "paper-qa": {
            "status": "complete",
            "score": {
                "total_vars": 10,
                "overall_score_exact": 0.2,
                "overall_score": 0.3,
                "missing_ratio": 0.4,
            },
        },
        "rich": {
            "status": "complete",
            "score": {
                "total_vars": 10,
                "overall_score_exact": 0.8,
                "overall_score": 0.9,
                "missing_ratio": 0.1,
            },
        },
    }

    aggregates = _MODULE._partitioned_aggregates(records)

    assert aggregates["all"]["overall_score_exact"] == 0.5
    assert aggregates["development"]["overall_score_exact"] == 0.2
    assert aggregates["holdout"]["overall_score_exact"] == 0.8


def test_command_group_returns_child_exit_status() -> None:
    assert _MODULE._run_command_group(
        [sys.executable, "-c", "raise SystemExit(7)"], timeout=5
    ) == 7


def test_full_terminal_selection_includes_failure_fallbacks_but_not_live_runs():
    manifest = {"repositories": {
        "complete": {"status": "complete"},
        "partial": {"status": "partial"},
        "timeout": {"status": "timed_out"},
        "failure": {"status": "failed"},
        "live": {"status": "running"},
        "unknown": {"status": "unrecognized"},
    }}
    assert _MODULE._eligible_repositories(
        manifest, selected=None, include_partial=False, include_incomplete=True,
    ) == ["complete", "failure", "partial", "timeout"]
    assert _MODULE._eligible_repositories(
        manifest, selected={"timeout", "live"}, include_partial=False,
        include_incomplete=True,
    ) == ["timeout"]
    # Existing opt-in partial scoring still excludes timeouts and failures.
    assert _MODULE._eligible_repositories(
        manifest, selected=None, include_partial=True,
    ) == ["complete", "partial"]


def test_resumed_subset_excludes_old_scores_and_exposes_unscored_selection():
    manifest = {"selection": {"eligible_repositories": ["rich", "paper-qa", "flake8"]}}
    records = {
        "rich": {"status": "complete", "score": {"total_vars": 10, "overall_score_exact": 0.2}},
        "black": {"status": "complete", "score": {"total_vars": 990, "overall_score_exact": 1.0}},
        "paper-qa": {"status": "unavailable", "reason": "docker_image_missing"},
    }
    _MODULE._update_aggregates(manifest, records)
    assert manifest["aggregate"]["total_vars"] == 10
    assert manifest["aggregate"]["overall_score_exact"] == 0.2
    assert manifest["coverage"] == {
        "eligible_repositories": 3,
        "scored_repositories": 1,
        "unscored_repositories": {"paper-qa": "unavailable", "flake8": "pending"},
    }
    assert "black" in records  # Historical result is retained, excluded from this selection.


def test_missing_images_produce_accountable_incomplete_score_manifest(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(_MODULE.json.dumps({"repositories": {
        "rich": {"status": "failed", "files_failed": 12},
        "paper-qa": {"status": "complete", "files_failed": 0},
        "black": {"status": "running"},
    }}))
    monkeypatch.setattr(_MODULE, "local_docker_images", lambda: set())
    monkeypatch.setattr(sys, "argv", [
        "score", str(run), str(tmp_path / "corpus"), str(tmp_path / "scorer"),
        "--include-incomplete", "--no-resume",
    ])
    _MODULE.main()
    manifest = _MODULE.json.loads((run / "score-manifest.json").read_text())
    assert manifest["run_status"] == "finished_with_incomplete_repositories"
    assert manifest["coverage"]["eligible_repositories"] == 2
    assert manifest["coverage"]["scored_repositories"] == 0
    assert manifest["coverage"]["unscored_repositories"] == {
        "rich": "unavailable", "paper-qa": "unavailable",
    }
    assert manifest["selection"]["excluded_repositories"] == {"black": "running"}
    assert manifest["analysis_outcomes"]["rich"]["files_failed"] == 12


@pytest.mark.parametrize("previous_status", ["failed", "unavailable", "running"])
def test_resume_unattempted_preserves_failures_and_rejects_unresolved_outcomes(tmp_path, monkeypatch, previous_status):
    run = tmp_path / "run"
    run.mkdir()
    (run / "manifest.json").write_text(_MODULE.json.dumps({"repositories": {
        "old": {"status": "complete"}, "new": {"status": "complete"},
    }}))
    previous = {"status": previous_status, "error": "retained original evidence"}
    (run / "score-manifest.json").write_text(_MODULE.json.dumps({
        "predictions_root": str((run / "predictions").resolve()),
        "repositories": {"old": previous},
    }))
    monkeypatch.setattr(_MODULE, "local_docker_images", lambda: set())
    monkeypatch.setattr(sys, "argv", [
        "score", str(run), str(tmp_path / "corpus"), str(tmp_path / "scorer"),
        "--resume-unattempted",
    ])
    if previous_status == "running":
        with pytest.raises(RuntimeError, match="unresolved scoring outcome"):
            _MODULE.main()
    else:
        _MODULE.main()
        manifest = _MODULE.json.loads((run / "score-manifest.json").read_text())
        assert manifest["repositories"]["old"] == previous
        assert manifest["repositories"]["new"]["status"] == "unavailable"
        assert manifest["coverage"]["eligible_repositories"] == 2
        assert manifest["run_status"] == "finished_with_incomplete_repositories"
