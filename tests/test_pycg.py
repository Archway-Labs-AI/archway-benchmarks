from __future__ import annotations

import json
import multiprocessing
import time
from pathlib import Path

import pytest

from archway_benchmarks.pycg import (
    _callee_display_name,
    _inline_synthetic_frame_edges,
    _load_case_sources,
    EdgeScore,
    expected_edges_from_callgraph,
    load_cases,
    load_macro_cases,
    run_archway_pycg,
    score_adjacency_lists,
    score_edges,
)


def _write_case(root: Path, category: str, name: str, callgraph: dict) -> Path:
    case_root = root / "micro-benchmark" / "snippets" / category / name
    case_root.mkdir(parents=True)
    (case_root / "main.py").write_text("def f():\n    pass\n", encoding="utf-8")
    (case_root / "callgraph.json").write_text(
        json.dumps(callgraph),
        encoding="utf-8",
    )
    return case_root


def test_expected_edges_from_callgraph():
    assert expected_edges_from_callgraph({"main": ["main.f"], "main.f": []}) == {
        ("main", "main.f")
    }


def test_score_edges():
    score = score_edges(
        {("main", "main.f"), ("main.f", "main.g")},
        {("main", "main.f"), ("main", "main.x")},
    )
    assert score == EdgeScore(true_positive=1, false_positive=1, false_negative=1)
    assert score.precision == 0.5
    assert score.recall == 0.5
    assert score.f1 == 0.5


def test_score_adjacency_lists_preserves_official_duplicate_recall_denominator():
    score = score_adjacency_lists(
        {"main": ["main.f", "main.f", "main.g"]},
        {("main", "main.f"), ("main", "main.x")},
    )

    assert score.true_positive == 1
    assert score.recall_true_positive == 2
    assert score.false_positive == 1
    assert score.false_negative == 1
    assert score.precision == 0.5
    assert score.recall == 2 / 3


def test_callee_display_name_renders_external_dependency_call():
    assert (
        _callee_display_name(
            "sid:v1:external-dependency-call:streamlit.write",
            {},
        )
        == "streamlit.write"
    )


def test_inline_synthetic_frame_edges_projects_comprehension_calls():
    assert _inline_synthetic_frame_edges(
        {
            ("main", "main.<listcomp>"),
            ("main.<listcomp>", "main.func"),
            ("main.<listcomp>", "<builtin>.iter"),
            ("main.<listcomp>", "<builtin-method>.list.append"),
        }
    ) == {("main", "main.func")}


def test_inline_synthetic_frame_edges_handles_nested_comprehensions():
    assert _inline_synthetic_frame_edges(
        {
            ("main", "main.<listcomp>"),
            ("main.<listcomp>", "main.<listcomp>.<listcomp>"),
            ("main.<listcomp>", "main.func1"),
            ("main.<listcomp>.<listcomp>", "main.func2"),
        }
    ) == {("main", "main.func1"), ("main", "main.func2")}


def test_inline_synthetic_frame_edges_filters_direct_implementation_helpers():
    assert _inline_synthetic_frame_edges(
        {
            ("main", "<builtin>.iter"),
            ("main", "<**PyDict**>.update"),
            ("main", "main.func"),
        }
    ) == {("main", "main.func")}


def test_load_cases_reads_pycg_micro_layout(tmp_path: Path):
    _write_case(tmp_path, "direct_calls", "call", {"main": ["main.f"]})

    (case,) = load_cases(tmp_path)

    assert case.suite_path == "direct_calls/call"
    assert case.main_path.name == "main.py"
    assert case.expected_edges == frozenset({("main", "main.f")})


def test_load_cases_requires_pycg_layout(tmp_path: Path):
    missing = tmp_path / "missing"
    try:
        load_cases(missing)
    except FileNotFoundError as exc:
        assert "micro-benchmark/snippets" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("load_cases should reject missing PyCG layout")


def test_load_macro_cases_reads_official_project_layout(tmp_path: Path):
    macro_root = tmp_path / "data" / "macro-benchmark"
    projects = macro_root / "projects"
    ground_truth = macro_root / "ground-truth-cgs"
    ground_truth.mkdir(parents=True)

    for name in ("autojump", "fabric", "asciinema", "face_classification", "Sublist3r"):
        (projects / name).mkdir(parents=True)
        (ground_truth / f"{name}.json").write_text(
            json.dumps({f"{name}.caller": [f"{name}.callee"]}),
            encoding="utf-8",
        )

    (projects / "autojump" / "bin").mkdir()
    (projects / "autojump" / "bin" / "autojump.py").write_text("def f():\n    pass\n")
    (projects / "fabric" / "fabric").mkdir()
    (projects / "fabric" / "fabric" / "api.py").write_text("def f():\n    pass\n")
    (projects / "fabric" / "tests").mkdir()
    (projects / "fabric" / "tests" / "test_api.py").write_text("def test_f():\n    pass\n")
    (projects / "fabric" / "setup.py").write_text("from setuptools import setup\n")
    (projects / "asciinema" / "asciinema").mkdir()
    (projects / "asciinema" / "asciinema" / "api.py").write_text("def f():\n    pass\n")
    (projects / "face_classification" / "src" / "models").mkdir(parents=True)
    (projects / "face_classification" / "src" / "models" / "cnn.py").write_text(
        "def f():\n    pass\n"
    )
    (projects / "Sublist3r" / "subbrute").mkdir()
    (projects / "Sublist3r" / "sublist3r.py").write_text("def f():\n    pass\n")
    (projects / "Sublist3r" / "subbrute" / "__init__.py").write_text("")

    cases = load_macro_cases(tmp_path)

    assert [case.suite_path for case in cases] == [
        "autojump",
        "fabric",
        "asciinema",
        "face_classification",
        "Sublist3r",
    ]
    fabric = next(case for case in cases if case.suite_path == "fabric")
    assert [path.name for path in fabric.source_paths] == ["api.py"]
    assert fabric.expected_edges == frozenset({("fabric.caller", "fabric.callee")})

    sources = _load_case_sources(next(case for case in cases if case.suite_path == "Sublist3r"))
    assert set(sources) == {"subbrute", "sublist3r"}
    assert sources["subbrute"] == "pass\n"


def test_load_cases_accepts_macro_suite(tmp_path: Path):
    macro_root = tmp_path / "data" / "macro-benchmark"
    (macro_root / "projects" / "autojump" / "bin").mkdir(parents=True)
    (macro_root / "projects" / "autojump" / "bin" / "autojump.py").write_text("x = 1\n")
    (macro_root / "ground-truth-cgs").mkdir(parents=True)
    (macro_root / "ground-truth-cgs" / "autojump.json").write_text("{}")

    for name in ("fabric", "asciinema", "face_classification", "Sublist3r"):
        (macro_root / "projects" / name).mkdir(parents=True)
        (macro_root / "ground-truth-cgs" / f"{name}.json").write_text("{}")
    (macro_root / "projects" / "fabric" / "fabric").mkdir()
    (macro_root / "projects" / "asciinema" / "asciinema").mkdir()
    (macro_root / "projects" / "face_classification" / "src").mkdir()

    (case,) = load_cases(tmp_path, suite="macro", limit=1)

    assert case.suite == "macro"
    assert case.suite_path == "autojump"


def test_run_archway_pycg_logs_case_progress_to_stderr(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    _write_case(tmp_path, "direct_calls", "call", {"main": ["main.f"]})

    def fake_archway_call_edges(*args, **kwargs):
        return {("main", "main.f")}

    monkeypatch.setattr(
        "archway_benchmarks.pycg.archway_call_edges",
        fake_archway_call_edges,
    )

    result = run_archway_pycg(corpus_root=tmp_path, engine_root=tmp_path)

    assert result.cases_ok == 1
    stderr = capsys.readouterr().err
    assert "PyCG micro case 1/1 direct_calls/call: start elapsed=" in stderr
    assert "PyCG micro case 1/1 direct_calls/call: ok case_elapsed=" in stderr
    assert "predicted_edges=1" in stderr


def test_run_archway_pycg_timeout_marks_case_without_predictions(
    tmp_path: Path,
    monkeypatch,
):
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("timeout test requires fork multiprocessing support")
    _write_case(tmp_path, "direct_calls", "call", {"main": ["main.f"]})

    def slow_archway_call_edges(*args, **kwargs):
        time.sleep(1)
        return {("main", "main.f")}

    monkeypatch.setattr(
        "archway_benchmarks.pycg.archway_call_edges",
        slow_archway_call_edges,
    )

    result = run_archway_pycg(
        corpus_root=tmp_path,
        engine_root=tmp_path,
        case_timeout_seconds=0.05,
    )

    assert result.cases_ok == 0
    assert result.cases_error == 1
    assert result.predicted_edges_total == 0
    assert result.cases[0].status == "timeout"
    assert result.cases[0].predicted_edge_count == 0
    assert result.cases[0].predicted_edges == ()
