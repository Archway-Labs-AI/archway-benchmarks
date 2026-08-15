from pathlib import Path

import pytest

from archway_benchmarks.typybench_harness import (
    REQUIRED_RESULT_COLUMNS,
    available_repos,
    build_command,
    docker_image_name,
    missing_docker_images,
    materialize_source_prediction,
    parse_result_csv,
    validate_repo_source_trees,
    score_command,
    stage_single_repo_prediction_root,
)


def test_parse_result_csv_normalizes_numbers_and_na(tmp_path: Path) -> None:
    csv_path = tmp_path / "agents_results_w_exact.csv"
    row = {
        "repo_name": "agents",
        "total_vars": "1956",
        "overall_score": "0.7743",
        "overall_score_wo_missing": "0.8825",
        "overall_score_exact": "0.7076",
        "overall_score_wo_missing_exact": "0.8065",
        "missing_ratio": "0.1227",
        "depth_1_score": "0.7660",
        "depth_2_score": "0.8140",
        "depth_3_score": "0.6947",
        "depth_4_score": "0.0000",
        "depth_5_score": "N/A",
        "depth_1_score_exact": "0.7112",
        "depth_2_score_exact": "0.7200",
        "depth_3_score_exact": "0.5111",
        "depth_4_score_exact": "0.0000",
        "depth_5_score_exact": "N/A",
        "repo_a_consistency": "71",
        "repo_b_consistency": "339",
        "lower_than_5_average": "0.7533",
        "lower_than_10_average": "0.7407",
        "lower_than_5_average_exact": "0.6923",
        "lower_than_10_average_exact": "0.6816",
    }
    csv_path.write_text(
        ",".join(REQUIRED_RESULT_COLUMNS)
        + "\n"
        + ",".join(row[col] for col in REQUIRED_RESULT_COLUMNS)
        + "\n"
    )

    result = parse_result_csv(csv_path)

    assert result.repo_name == "agents"
    assert result.total_vars == 1956
    assert result.overall_score == pytest.approx(0.7743)
    assert result.values["depth_5_score"] is None
    assert result.repo_a_consistency_errors == 71
    assert result.repo_b_consistency_errors == 339


def test_materialize_source_prediction_copies_only_python_sources(tmp_path: Path) -> None:
    source = tmp_path / "repo" / "original_repo"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg" / "__init__.py").write_text("")
    (source / "pkg" / "mod.py").write_text("def f(x: int) -> int:\n    return x\n")
    (source / "README.md").write_text("not copied")

    dest = materialize_source_prediction(
        repo_name="demo",
        source_root=source,
        predictions_root=tmp_path / "predictions",
    )

    assert (dest / "pkg" / "__init__.py").exists()
    assert (dest / "pkg" / "mod.py").exists()
    assert not (dest / "README.md").exists()


def test_materialize_source_prediction_rejects_empty_source_tree(tmp_path: Path) -> None:
    source = tmp_path / "repo" / "original_repo"
    source.mkdir(parents=True)
    (source / ".DS_Store").write_text("")

    with pytest.raises(ValueError, match="contains no Python source files"):
        materialize_source_prediction(
            repo_name="demo",
            source_root=source,
            predictions_root=tmp_path / "predictions",
        )

    assert not (tmp_path / "predictions" / "demo").exists()


def test_stage_single_repo_prediction_root_contains_only_requested_repo(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions"
    (predictions / "agents").mkdir(parents=True)
    (predictions / "agents" / "a.py").write_text("x = 1\n")
    (predictions / "other").mkdir()
    (predictions / "other" / "b.py").write_text("y = 1\n")

    staging_root = stage_single_repo_prediction_root(
        repo_name="agents",
        predictions_root=predictions,
        staging_root=tmp_path / "single",
    )

    assert sorted(path.name for path in staging_root.iterdir()) == ["agents"]
    assert (staging_root / "agents").is_symlink()
    assert (staging_root / "agents" / "a.py").read_text() == "x = 1\n"


def test_stage_single_repo_prediction_root_rejects_empty_prediction_tree(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions"
    (predictions / "agents").mkdir(parents=True)
    (predictions / "agents" / ".DS_Store").write_text("")

    with pytest.raises(ValueError, match="prediction directory.*contains no Python source files"):
        stage_single_repo_prediction_root(
            repo_name="agents",
            predictions_root=predictions,
            staging_root=tmp_path / "single",
        )

    assert not (tmp_path / "single").exists()


def test_stage_single_repo_replaces_legacy_root_symlink_without_touching_source(
    tmp_path: Path,
) -> None:
    predictions = tmp_path / "predictions"
    source = predictions / "gptme"
    package = source / "gptme"
    package.mkdir(parents=True)
    module = package / "__init__.py"
    module.write_text("value = 1\n")
    staging_root = tmp_path / "staging" / "gptme"
    staging_root.parent.mkdir()
    staging_root.symlink_to(source, target_is_directory=True)

    stage_single_repo_prediction_root(
        repo_name="gptme",
        predictions_root=predictions,
        staging_root=staging_root,
    )

    assert staging_root.is_dir() and not staging_root.is_symlink()
    assert (staging_root / "gptme").is_symlink()
    assert module.read_text() == "value = 1\n"


def test_validate_repo_source_trees_rejects_zero_source_fixture(tmp_path: Path) -> None:
    data = tmp_path / "typybenchdata"
    for tree_name in ("repo_without_types", "original_repo"):
        tree = data / "pylint" / tree_name
        tree.mkdir(parents=True)
        (tree / ".DS_Store").write_text("")

    with pytest.raises(ValueError, match="TypyBench repo 'pylint' repo_without_types"):
        validate_repo_source_trees("pylint", data_path=data)


def test_commands_match_upstream_run_py_shape(tmp_path: Path) -> None:
    tool = tmp_path / "typybench"
    data = tmp_path / "typybenchdata"
    pred = tmp_path / "predictions"

    assert build_command(typybench_root=tool, data_path=data, repo="agents") == [
        "python3",
        str(tool / "run.py"),
        "--data-path",
        str(data),
        "--num-workers",
        "1",
        "--build",
        "--repo",
        "agents",
    ]
    assert score_command(
        typybench_root=tool,
        data_path=data,
        pred_path=pred,
        num_workers=2,
        repo="agents",
    ) == [
        "python3",
        str(tool / "run.py"),
        "--data-path",
        str(data),
        "--num-workers",
        "2",
        "--pred-path",
        str(pred),
        "--repo",
        "agents",
    ]
    assert score_command(
        typybench_root=tool,
        data_path=data,
        pred_path=pred,
        progress_jsonl=tmp_path / "progress.jsonl",
        log_dir=tmp_path / "repo-logs",
        skip_completed=True,
    ) == [
        "python3",
        str(tool / "run.py"),
        "--data-path",
        str(data),
        "--num-workers",
        "1",
        "--pred-path",
        str(pred),
        "--progress-jsonl",
        str(tmp_path / "progress.jsonl"),
        "--log-dir",
        str(tmp_path / "repo-logs"),
        "--skip-completed",
    ]


def test_available_repos_and_missing_docker_images(tmp_path: Path) -> None:
    data = tmp_path / "typybenchdata"
    (data / "AutoGPT").mkdir(parents=True)
    (data / "paper-qa").mkdir()
    (data / ".cache").mkdir()
    (data / "split.json").write_text("{}")

    assert available_repos(data) == ["AutoGPT", "paper-qa"]
    assert docker_image_name("AutoGPT") == "typybench-autogpt"
    assert missing_docker_images(
        data_path=data,
        local_images={"typybench-paper-qa"},
    ) == ["AutoGPT"]
