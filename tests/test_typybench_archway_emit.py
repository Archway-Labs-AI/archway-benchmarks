import ast
import json
import sys

from archway_benchmarks.typybench_archway_emit import (
    _annotate_source,
    _element_type,
    _function_types,
    _run_engine_probe,
    capture_translation_trace_file,
    emit_archway_predictions,
)


def test_annotate_source_inserts_params_returns_and_typing_import() -> None:
    source = '''"""module docstring"""

def f(x, y=1):
    return x

async def g(items, **kwargs):
    return items
'''
    function_types = {
        (3, "f"): {"params": {"x": "int", "y": "Union[int, str]"}, "return": "Any"},
        (6, "g"): {
            "params": {"items": "list[str]", "kwargs": "dict[str, int]"},
            "return": "list[str]",
        },
    }

    annotated, stats = _annotate_source(source, function_types)

    ast.parse(annotated)
    assert "from typing import Any, Union" in annotated
    assert "def f(x: int, y: Union[int, str]=1) -> Any:" in annotated
    assert "async def g(items: list[str], **kwargs: dict[str, int]) -> list[str]:" in annotated
    assert stats == {"functions": 2, "params": 4, "returns": 2}


def test_annotate_source_preserves_existing_annotations() -> None:
    source = "def f(x: str) -> str:\n    return x\n"
    function_types = {(1, "f"): {"params": {"x": "int"}, "return": "int"}}

    annotated, stats = _annotate_source(source, function_types)

    assert "def f(x: str) -> str:" in annotated
    assert stats == {"functions": 0, "params": 0, "returns": 0}


def test_annotate_source_places_typing_import_after_future_imports() -> None:
    source = '''"""module docstring"""
from __future__ import annotations

def f(x):
    return x
'''
    function_types = {(4, "f"): {"params": {"x": "Any"}, "return": "Any"}}

    annotated, stats = _annotate_source(source, function_types)

    ast.parse(annotated)
    future_at = annotated.index("from __future__ import annotations")
    typing_at = annotated.index("from typing import Any, Union")
    assert future_at < typing_at
    assert stats == {"functions": 1, "params": 1, "returns": 1}


def test_function_types_extracts_signatures_from_engine_projection() -> None:
    analysis = {
        "functions": [
            {
                "fn_id": 1,
                "name": "f",
                "source_position": {"row": 10},
                "instantiations": [
                    {
                        "params": {"x": [{"element": {"kind": "pytype", "name": "builtins.int"}}]},
                        "ret": {"element": {"kind": "list", "element": {"kind": "pytype", "name": "builtins.str"}}},
                    },
                    {
                        "params": {"x": [{"element": {"kind": "pytype", "name": "builtins.str"}}]},
                        "ret": {"element": {"kind": "none"}},
                    },
                ],
            }
        ]
    }

    assert _function_types(analysis) == {
        (10, "f"): {"params": {"x": "Union[int, str]"}, "return": "Union[None, list[str]]"}
    }


def test_function_types_normalizes_builtins_nonetype() -> None:
    analysis = {
        "functions": [
            {
                "fn_id": 1,
                "name": "main",
                "source_position": {"row": 1},
                "instantiations": [
                    {
                        "params": {
                            "argv": [
                                {"element": {"kind": "pytype", "name": "builtins.NoneType"}}
                            ]
                        },
                        "ret": {"element": {"kind": "pytype", "name": "NoneType"}},
                    },
                ],
            }
        ]
    }

    assert _function_types(analysis) == {
        (1, "main"): {"params": {"argv": "None"}, "return": "None"}
    }


def test_builtins_nonetype_renders_as_parseable_none_annotations() -> None:
    source = "def main(argv=None):\n    return None\n"
    analysis = {
        "functions": [
            {
                "fn_id": 1,
                "name": "main",
                "source_position": {"row": 1},
                "instantiations": [
                    {
                        "params": {
                            "argv": [
                                {"element": {"kind": "pytype", "name": "builtins.NoneType"}}
                            ]
                        },
                        "ret": {"element": {"kind": "pytype", "name": "NoneType"}},
                    }
                ],
            }
        ]
    }

    annotated, stats = _annotate_source(source, _function_types(analysis))

    ast.parse(annotated)
    assert "NoneType" not in annotated
    assert "def main(argv: None=None) -> None:" in annotated
    assert stats == {"functions": 1, "params": 1, "returns": 1}


def test_generator_element_renders_as_parseable_generator_annotation() -> None:
    source = "def numbers():\n    yield 1\n"
    analysis = {
        "functions": [
            {
                "fn_id": 1,
                "name": "numbers",
                "source_position": {"row": 1},
                "instantiations": [
                    {
                        "params": {},
                        "ret": {
                            "element": {
                                "kind": "generator",
                                "element": {"kind": "pytype", "name": "builtins.int"},
                            }
                        },
                    }
                ],
            }
        ]
    }

    function_types = _function_types(analysis)
    annotated, stats = _annotate_source(source, function_types)

    assert function_types == {
        (1, "numbers"): {"params": {}, "return": "Generator[int, None, None]"}
    }
    ast.parse(annotated)
    assert "unknown kind: generator" not in annotated
    assert "from typing import Generator" in annotated
    assert "def numbers() -> Generator[int, None, None]:" in annotated
    assert stats == {"functions": 1, "params": 0, "returns": 1}


def test_ellipsis_pytype_renders_as_any_fallback_instead_of_lowercase_name() -> None:
    analysis = {
        "functions": [
            {
                "fn_id": 1,
                "name": "f",
                "source_position": {"row": 1},
                "instantiations": [
                    {
                        "params": {
                            "x": [{"element": {"kind": "pytype", "name": "ellipsis"}}]
                        },
                        "ret": {"element": {"kind": "pytype", "name": "builtins.int"}},
                    }
                ],
            }
        ]
    }

    assert _function_types(analysis) == {
        (1, "f"): {"params": {"x": "Any"}, "return": "int"}
    }


def test_element_type_maps_supported_shapes() -> None:
    by_id = {7: {"name": "Factory"}}

    assert _element_type({"kind": "top"}, by_id) == "Any"
    assert _element_type({"kind": "dict", "key": {"kind": "pytype", "name": "builtins.str"}, "value": {"kind": "none"}}, by_id) == "dict[str, None]"
    assert _element_type({"kind": "instance", "cls": {"body": 7}}, by_id) == "Factory"


def test_element_type_resolves_string_body_ids() -> None:
    by_id = {"sid:v1:body:factory": {"name": "Factory"}}

    assert (
        _element_type({"kind": "instance", "cls": {"body": "sid:v1:body:factory"}}, by_id)
        == "Factory"
    )


def test_renderer_keeps_container_elements_and_parseable_union_spelling() -> None:
    source = "def f(items, lookup, pair):\n    return pair\n"
    analysis = {
        "functions": [
            {
                "fn_id": 1,
                "name": "f",
                "source_position": {"row": 1},
                "instantiations": [
                    {
                        "params": {
                            "items": [
                                {
                                    "element": {
                                        "kind": "list",
                                        "element": {"kind": "pytype", "name": "builtins.str"},
                                    }
                                }
                            ],
                            "lookup": [
                                {
                                    "element": {
                                        "kind": "dict",
                                        "key": {"kind": "pytype", "name": "builtins.str"},
                                        "value": {"kind": "pytype", "name": "builtins.int"},
                                    }
                                }
                            ],
                            "pair": [
                                {
                                    "element": {
                                        "kind": "tuple",
                                        "slots": [
                                            {"kind": "pytype", "name": "builtins.int"},
                                            {"kind": "pytype", "name": "builtins.str"},
                                        ],
                                    }
                                }
                            ],
                        },
                        "ret": {
                            "element": {
                                "kind": "union",
                                "elements": [
                                    {"kind": "pytype", "name": "builtins.NoneType"},
                                    {"kind": "pytype", "name": "builtins.int"},
                                ],
                            }
                        },
                    }
                ],
            }
        ]
    }

    function_types = _function_types(analysis)
    annotated, stats = _annotate_source(source, function_types)

    ast.parse(annotated)
    assert "builtins." not in annotated
    assert "Optional" not in annotated
    assert "def f(items: list[str], lookup: dict[str, int], pair: tuple[int, str]) -> Union[None, int]:" in annotated
    assert "from typing import Any, Union" in annotated
    assert stats == {"functions": 1, "params": 3, "returns": 1}


def test_emit_predictions_leaves_original_source_on_invalid_annotation_syntax(tmp_path) -> None:
    engine = tmp_path / "engine"
    sd_core = engine / "sd_core"
    sd_core.mkdir(parents=True)
    (sd_core / "__init__.py").write_text("", encoding="utf-8")
    (sd_core / "analysis_server.py").write_text(
        """
def analyze_source(source, module_name):
    return {
        "functions": [
            {
                "fn_id": 1,
                "name": "f",
                "source_position": {"row": 1},
                "instantiations": [
                    {
                        "params": {"x": [{"element": {"kind": "pytype", "name": "list["}}]},
                        "ret": {"element": {"kind": "pytype", "name": "builtins.int"}},
                    }
                ],
            }
        ]
    }
""",
        encoding="utf-8",
    )

    source_root = tmp_path / "repo"
    source_root.mkdir()
    original = "def f(x):\n    return x\n"
    (source_root / "demo.py").write_text(original, encoding="utf-8")

    stats = emit_archway_predictions(
        repo_name="demo",
        untyped_root=source_root,
        predictions_root=tmp_path / "predictions",
        engine_worktree=engine,
        runner=(sys.executable,),
        timeout=30,
        per_file_timeout=5,
    )

    assert (tmp_path / "predictions" / "demo" / "demo.py").read_text(encoding="utf-8") == original
    assert stats.failures
    assert "emit SyntaxError" in stats.failures[0]["error"]


def test_run_engine_probe_records_per_file_failures(tmp_path) -> None:
    engine = tmp_path / "engine"
    sd_core = engine / "sd_core"
    sd_core.mkdir(parents=True)
    (sd_core / "__init__.py").write_text("", encoding="utf-8")
    (sd_core / "analysis_server.py").write_text(
        """
def analyze_source(source, module_name):
    if "raise_me" in source:
        raise ValueError("synthetic failure")
    return {"functions": []}
""",
        encoding="utf-8",
    )

    source_root = tmp_path / "repo"
    source_root.mkdir()
    (source_root / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (source_root / "bad.py").write_text("raise_me = True\n", encoding="utf-8")

    payload = _run_engine_probe(
        engine_worktree=engine,
        source_root=source_root,
        runner=(sys.executable,),
        timeout=30,
        per_file_timeout=5,
    )

    assert payload["files"]["ok.py"]["ok"] is True
    assert payload["files"]["bad.py"]["ok"] is False
    assert "ValueError: synthetic failure" in payload["files"]["bad.py"]["error"]


def test_emit_predictions_copies_all_sources_before_analysis_timeout(tmp_path) -> None:
    engine = tmp_path / "engine"
    sd_core = engine / "sd_core"
    sd_core.mkdir(parents=True)
    (sd_core / "__init__.py").write_text("", encoding="utf-8")
    (sd_core / "analysis_server.py").write_text(
        """
import time

def analyze_source(source, module_name):
    time.sleep(2)
    return {"functions": []}
""",
        encoding="utf-8",
    )

    source_root = tmp_path / "repo"
    (source_root / "pkg").mkdir(parents=True)
    (source_root / "pkg" / "a.py").write_text("def a(x):\n    return x\n", encoding="utf-8")
    (source_root / "pkg" / "b.py").write_text("def b(y):\n    return y\n", encoding="utf-8")

    stats = emit_archway_predictions(
        repo_name="demo",
        untyped_root=source_root,
        predictions_root=tmp_path / "predictions",
        engine_worktree=engine,
        runner=(sys.executable,),
        timeout=1,
        per_file_timeout=1,
    )

    dest = tmp_path / "predictions" / "demo"
    assert (dest / "pkg" / "a.py").read_text(encoding="utf-8") == "def a(x):\n    return x\n"
    assert (dest / "pkg" / "b.py").read_text(encoding="utf-8") == "def b(y):\n    return y\n"
    assert stats.files_total == 2
    assert stats.files_failed == 2


def test_emit_predictions_trace_jsonl_records_raw_rendered_and_insertion(tmp_path) -> None:
    engine = tmp_path / "engine"
    sd_core = engine / "sd_core"
    sd_core.mkdir(parents=True)
    (sd_core / "__init__.py").write_text("", encoding="utf-8")
    (sd_core / "analysis_server.py").write_text(
        """
def analyze_source(source, module_name):
    return {
        "functions": [
            {
                "fn_id": 1,
                "name": "f",
                "source_position": {"row": 1},
                "instantiations": [
                    {
                        "params": {
                            "x": [{"element": {"kind": "pytype", "name": "builtins.int"}}],
                            "y": [{"element": {"kind": "list"}}],
                            "z": [{"element": {"kind": "pytype", "name": "builtins.str"}}],
                        },
                        "ret": {"element": {"kind": "top"}},
                    }
                ],
            }
        ]
    }
""",
        encoding="utf-8",
    )

    source_root = tmp_path / "repo"
    source_root.mkdir()
    (source_root / "demo.py").write_text("def f(x, y: str) -> bool:\n    return y\n", encoding="utf-8")
    trace_jsonl = tmp_path / "trace" / "typybench.jsonl"

    stats = emit_archway_predictions(
        repo_name="demo",
        untyped_root=source_root,
        predictions_root=tmp_path / "predictions",
        engine_worktree=engine,
        runner=(sys.executable,),
        timeout=30,
        per_file_timeout=5,
        trace_jsonl=trace_jsonl,
    )

    assert stats.params_annotated == 1
    records = [json.loads(line) for line in trace_jsonl.read_text(encoding="utf-8").splitlines()]
    by_slot = {record["slot"]: record for record in records}
    assert by_slot["param:x"]["raw_candidates"][0]["raw_elements"] == [
        {"kind": "pytype", "name": "builtins.int"}
    ]
    assert by_slot["param:x"]["rendered_annotation"] == "int"
    assert by_slot["param:x"]["insertion_happened"] is True
    assert by_slot["param:x"]["final_annotation"] == "int"
    assert by_slot["param:y"]["rendered_annotation"] == "list[Any]"
    assert by_slot["param:y"]["insertion_happened"] is False
    assert by_slot["param:y"]["insertion_reason"] == "existing annotation preserved"
    assert by_slot["param:y"]["fallback_reason"] == "list.element: missing element"
    assert by_slot["param:z"]["insertion_reason"] == "parameter not present in AST"
    assert by_slot["return"]["rendered_annotation"] == "Any"
    assert by_slot["return"]["fallback_reason"] == "top"
    assert by_slot["return"]["final_annotation"] == "bool"


def test_emit_predictions_profile_jsonl_records_per_file_timings(tmp_path) -> None:
    engine = tmp_path / "engine"
    sd_core = engine / "sd_core"
    sd_core.mkdir(parents=True)
    (sd_core / "__init__.py").write_text("", encoding="utf-8")
    (sd_core / "analysis_server.py").write_text(
        """
def analyze_source(source, module_name):
    if "boom" in source:
        raise RuntimeError("synthetic")
    return {
        "functions": [
            {
                "fn_id": 1,
                "name": "f",
                "source_position": {"row": 1},
                "instantiations": [
                    {
                        "params": {"x": [{"element": {"kind": "pytype", "name": "builtins.int"}}]},
                        "ret": {"element": {"kind": "pytype", "name": "builtins.int"}},
                    }
                ],
            }
        ]
    }
""",
        encoding="utf-8",
    )
    source_root = tmp_path / "repo"
    source_root.mkdir()
    (source_root / "ok.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
    (source_root / "bad.py").write_text("boom = True\n", encoding="utf-8")
    profile_jsonl = tmp_path / "profile" / "files.jsonl"

    stats = emit_archway_predictions(
        repo_name="demo",
        untyped_root=source_root,
        predictions_root=tmp_path / "predictions",
        engine_worktree=engine,
        runner=(sys.executable,),
        timeout=30,
        per_file_timeout=5,
        profile_jsonl=profile_jsonl,
    )

    rows = [json.loads(line) for line in profile_jsonl.read_text(encoding="utf-8").splitlines()]
    by_file = {row["file"]: row for row in rows}
    assert stats.file_profiles
    assert by_file["ok.py"]["status"] == "ok"
    assert by_file["ok.py"]["seconds_engine_probe"] >= 0
    assert by_file["ok.py"]["functions_seen"] == 1
    assert by_file["bad.py"]["status"] == "engine_failed"
    assert "RuntimeError: synthetic" in by_file["bad.py"]["error"]


def test_capture_translation_trace_file_writes_summary_and_text(tmp_path) -> None:
    engine = tmp_path / "engine"
    sd_core = engine / "sd_core"
    tooling = sd_core / "tooling"
    tracing = sd_core / "translate" / "tracing"
    tooling.mkdir(parents=True)
    tracing.mkdir(parents=True)
    (sd_core / "__init__.py").write_text("", encoding="utf-8")
    (tooling / "__init__.py").write_text("", encoding="utf-8")
    (sd_core / "translate" / "__init__.py").write_text("", encoding="utf-8")
    (tracing / "__init__.py").write_text(
        """
def format_trace(trace):
    return "TRACE:" + str(trace)
""",
        encoding="utf-8",
    )
    (tooling / "harness.py").write_text(
        """
class TranslationResult:
    def __init__(self):
        self.traces = ["root"]

    @classmethod
    def from_source(cls, source, trace=False, name=None):
        return cls()
""",
        encoding="utf-8",
    )
    source = tmp_path / "demo.py"
    source.write_text("x = 1\n", encoding="utf-8")

    summary = capture_translation_trace_file(
        engine_worktree=engine,
        source_path=source,
        module_name="demo",
        trace_dir=tmp_path / "traces",
        runner=(sys.executable,),
        timeout=5,
    )

    assert summary["ok"] is True
    assert summary["span_count"] == 0
    assert "TRACE:root" in (tmp_path / "traces" / "demo.py.trace.txt").read_text(
        encoding="utf-8"
    )
    assert (tmp_path / "traces" / "demo.py.trace-summary.json").exists()
