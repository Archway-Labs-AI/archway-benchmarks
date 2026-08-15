import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).parents[1] / "scripts" / "typybench_successor_score.py"
_SPEC = importlib.util.spec_from_file_location("typybench_successor_score", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


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

    prediction.touch()
    assert not _MODULE._result_is_current(result, prediction.parent)
