from __future__ import annotations

import json
from pathlib import Path

from archway_benchmarks.pycg import (
    _callee_display_name,
    _inline_synthetic_frame_edges,
    EdgeScore,
    expected_edges_from_callgraph,
    load_cases,
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
