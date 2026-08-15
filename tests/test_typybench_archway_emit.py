import ast
import json
import sys

import archway_benchmarks.typybench_archway_emit as emit_module
from archway_benchmarks.typybench_archway_emit import (
    _annotate_source,
    _element_type,
    _function_types,
    _probe_progress,
    _run_engine_probe,
    _successor_function_types,
    _successor_variable_types,
    capture_runtime_phase_profile_file,
    capture_translation_trace_file,
    emit_archway_predictions,
)


def test_probe_progress_retains_compact_timeout_evidence() -> None:
    progress = _probe_progress(
        "ARCHWAY_PHASE translation 8.125000\n"
        "ARCHWAY_PHASE signature_demands 3901\n"
        "ARCHWAY_PHASE body_roots 1105\n"
        "ARCHWAY_TRANSLATION_START pkg/slow.py\n"
        "ARCHWAY_TRANSLATION_DONE 1.500000 ok pkg/slow.py\n"
        "ARCHWAY_TRANSLATION_START pkg/active.py\n"
        'ARCHWAY_BODY_PLAN [["first","second"]]\n'
        "ARCHWAY_BODY 2/139 16.250000 exec=618 topology=5940 "
        "appworld.api_docs:generate_example\n"
    )

    assert progress == {
        "phase_progress": {
            "translation": 8.125,
            "signature_demands": 3901,
            "body_roots": 1105,
        },
        "body_plan": [["first", "second"]],
        "body_profiles": [{
            "index": 2,
            "total": 139,
            "seconds": 16.25,
            "executions": 618,
            "topology_changes": 5940,
            "label": "appworld.api_docs:generate_example",
        }],
        "active_translation_file": "pkg/active.py",
        "slow_translation_files": [{
            "seconds": 1.5,
            "status": "ok",
            "file": "pkg/slow.py",
        }],
    }


def test_emit_timeout_retains_repo_probe_progress(monkeypatch, tmp_path) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    (source_root / "demo.py").write_text("value = 1\n", encoding="utf-8")
    engine = tmp_path / "engine"
    engine.mkdir()
    progress = {
        "phase_progress": {"translation": 2.0, "body_roots": 12},
        "body_plan": [["module:slow"]],
        "body_profiles": [{
            "index": 1,
            "total": 12,
            "seconds": 30.0,
            "executions": 100,
            "topology_changes": 200,
            "label": "module:slow",
        }],
    }
    monkeypatch.setattr(
        emit_module,
        "_run_successor_repo_probe",
        lambda **_kwargs: {
            "ok": False,
            "error": "TimeoutExpired: analysis exceeded 1s",
            "trace_tail": "ARCHWAY_BODY 1/12",
            "analysis_summary": progress,
        },
    )

    stats = emit_module.emit_archway_predictions(
        repo_name="demo",
        untyped_root=source_root,
        predictions_root=tmp_path / "predictions",
        engine_worktree=engine,
        timeout=1,
    )

    assert stats.files_failed == 1
    profile = stats.file_profiles[0]
    assert profile.status == "engine_failed"
    assert profile.analysis_summary == progress
    assert profile.trace_tail == "ARCHWAY_BODY 1/12"


def test_successor_observations_render_function_signatures() -> None:
    observations = [
        {"line": 4, "name": "x", "kind": "parameter", "function": "f", "types": ["builtins.int"]},
        {"line": 4, "name": "f", "kind": "return", "function": None, "types": ["builtins.str"]},
    ]

    assert _successor_function_types(observations) == {
        (4, "f"): {"params": {"x": "int"}, "return": "str"}
    }


def test_successor_observations_match_qualified_methods_to_source_name() -> None:
    observations = [
        {
            "line": 4,
            "name": "enabled",
            "kind": "parameter",
            "function": "Environment.__init__",
            "types": ["builtins.bool"],
        },
        {
            "line": 4,
            "name": "__init__",
            "kind": "return",
            "function": "Environment.__init__",
            "types": ["builtins.NoneType"],
        },
    ]

    function_types = _successor_function_types(observations)
    assert function_types == {
        (4, "__init__"): {
            "params": {"enabled": "bool"},
            "return": "None",
        }
    }
    annotated, stats = _annotate_source(
        "class Environment:\n"
        "    marker = True\n"
        "\n"
        "    def __init__(self, enabled):\n"
        "        self.enabled = enabled\n",
        function_types,
    )
    assert "def __init__(self, enabled: bool) -> None:" in annotated
    assert stats == {"functions": 1, "params": 1, "returns": 1, "variables": 0}


def test_successor_variable_observations_annotate_class_and_instance_stores() -> None:
    observations = [
        {
            "line": 2,
            "name": "Model.value",
            "kind": "variable",
            "function": None,
            "types": ["builtins.int"],
        },
        {
            "line": 5,
            "name": "self.labels",
            "kind": "variable",
            "function": "Model.__init__",
            "types": ["builtins.list", "Any"],
        },
    ]

    variable_types = _successor_variable_types(observations)
    assert variable_types == {
        (2, "value"): "int",
        (5, "labels"): "Union[Any, list]",
    }
    annotated, stats = _annotate_source(
        "class Model:\n"
        "    value = 3\n"
        "\n"
        "    def __init__(self):\n"
        "        self.labels = []\n",
        {},
        variable_types=variable_types,
    )
    ast.parse(annotated)
    assert "from typing import Any, Union" in annotated
    assert "value: int = 3" in annotated
    assert "self.labels: Union[Any, list] = []" in annotated
    assert stats == {
        "functions": 0,
        "params": 0,
        "returns": 0,
        "variables": 2,
    }


def test_repository_emission_keeps_variable_annotations_opt_in(
    monkeypatch, tmp_path,
) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    (source_root / "demo.py").write_text("value = 1\n", encoding="utf-8")
    engine = tmp_path / "engine"
    engine.mkdir()
    record = {
        "ok": True,
        "files": {
            "demo.py": [{
                "line": 1,
                "name": "value",
                "kind": "variable",
                "function": None,
                "types": ["builtins.int"],
            }],
        },
        "translation_failures": {},
        "analysis_summary": {},
    }
    monkeypatch.setattr(
        emit_module, "_run_successor_repo_probe", lambda **_kwargs: record
    )

    default_root = tmp_path / "default"
    default = emit_archway_predictions(
        repo_name="demo",
        untyped_root=source_root,
        predictions_root=default_root,
        engine_worktree=engine,
    )
    opt_in_root = tmp_path / "opt-in"
    opted_in = emit_archway_predictions(
        repo_name="demo",
        untyped_root=source_root,
        predictions_root=opt_in_root,
        engine_worktree=engine,
        emit_variable_annotations=True,
    )

    assert (default_root / "demo" / "demo.py").read_text() == "value = 1\n"
    assert default.variables_annotated == 0
    assert "value: int = 1" in (
        opt_in_root / "demo" / "demo.py"
    ).read_text()
    assert opted_in.variables_annotated == 1


def test_repository_emission_can_include_diagram_class_fields_explicitly(
    monkeypatch, tmp_path,
) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    (source_root / "demo.py").write_text(
        "class Model:\n    value = 1\n", encoding="utf-8"
    )
    engine = tmp_path / "engine"
    engine.mkdir()
    monkeypatch.setattr(
        emit_module,
        "_run_successor_repo_probe",
        lambda **_kwargs: {
            "ok": True,
            "files": {"demo.py": [{
                "line": 2,
                "name": "Model.value",
                "kind": "variable",
                "function": None,
                "types": ["builtins.int"],
            }]},
            "translation_failures": {},
            "analysis_summary": {},
        },
    )

    stats = emit_archway_predictions(
        repo_name="demo",
        untyped_root=source_root,
        predictions_root=tmp_path / "predictions",
        engine_worktree=engine,
        emit_class_field_annotations=True,
    )

    assert "value: int = 1" in (
        tmp_path / "predictions" / "demo" / "demo.py"
    ).read_text()
    assert stats.variables_annotated == 1


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
    assert stats == {"functions": 2, "params": 4, "returns": 2, "variables": 0}


def test_annotate_source_preserves_existing_annotations() -> None:
    source = "def f(x: str) -> str:\n    return x\n"
    function_types = {(1, "f"): {"params": {"x": "int"}, "return": "int"}}

    annotated, stats = _annotate_source(source, function_types)

    assert "def f(x: str) -> str:" in annotated
    assert stats == {"functions": 0, "params": 0, "returns": 0, "variables": 0}


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
    assert stats == {"functions": 1, "params": 1, "returns": 1, "variables": 0}


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
    assert stats == {"functions": 1, "params": 1, "returns": 1, "variables": 0}


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
    assert stats == {"functions": 1, "params": 0, "returns": 1, "variables": 0}


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
    assert stats == {"functions": 1, "params": 3, "returns": 1, "variables": 0}


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


def test_emit_predictions_rejects_zero_source_repo_before_staging(tmp_path) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    source_root = tmp_path / "repo_without_types"
    source_root.mkdir()
    (source_root / ".DS_Store").write_text("", encoding="utf-8")

    try:
        emit_archway_predictions(
            repo_name="pylint",
            untyped_root=source_root,
            predictions_root=tmp_path / "predictions",
            engine_worktree=engine,
            runner=(sys.executable,),
        )
    except ValueError as exc:
        assert "TypyBench repo 'pylint' repo_without_types contains no Python source files" in str(exc)
    else:
        raise AssertionError("expected zero-source fixture validation to fail")

    assert not (tmp_path / "predictions" / "pylint").exists()


def test_emit_predictions_preserves_cookiecutter_template_paths(tmp_path) -> None:
    engine = tmp_path / "engine"
    sd_core = engine / "sd_core"
    sd_core.mkdir(parents=True)
    (sd_core / "__init__.py").write_text("", encoding="utf-8")
    (sd_core / "analysis_server.py").write_text(
        """
from pathlib import Path

def analyze_source(source, module_name):
    assert "{{cookiecutter.__root_folder}}" in source
    assert Path(__import__("sys").argv[1]).is_file()
    return {"functions": []}
""",
        encoding="utf-8",
    )

    source_root = tmp_path / "repo_without_types"
    template_dir = source_root / "taipy" / "templates" / "default" / "{{cookiecutter.__root_folder}}"
    template_dir.mkdir(parents=True)
    source = template_dir / "{{cookiecutter.__main_file}}.py"
    source.write_text('MARKER = "{{cookiecutter.__root_folder}}"\n', encoding="utf-8")

    stats = emit_archway_predictions(
        repo_name="taipy",
        untyped_root=source_root,
        predictions_root=tmp_path / "predictions",
        engine_worktree=engine,
        runner=(sys.executable,),
        timeout=30,
        per_file_timeout=5,
    )

    rel = "taipy/templates/default/{{cookiecutter.__root_folder}}/{{cookiecutter.__main_file}}.py"
    assert stats.files_total == 1
    assert stats.files_failed == 0
    assert (tmp_path / "predictions" / "taipy" / rel).is_file()


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


def test_emit_trace_records_slots_omitted_by_engine_projection(tmp_path) -> None:
    engine = tmp_path / "engine"
    sd_core = engine / "sd_core"
    sd_core.mkdir(parents=True)
    (sd_core / "__init__.py").write_text("", encoding="utf-8")
    (sd_core / "analysis_server.py").write_text(
        """
def analyze_source(source, module_name):
    return {
        "functions": [{
            "fn_id": 1,
            "name": "main",
            "source_position": {"row": 1},
            "instantiations": [{"params": {}, "ret": {}}],
        }]
    }
""",
        encoding="utf-8",
    )
    source_root = tmp_path / "repo"
    source_root.mkdir()
    (source_root / "demo.py").write_text(
        "def main(argv=None):\n    return 0\n",
        encoding="utf-8",
    )
    trace_jsonl = tmp_path / "trace.jsonl"

    emit_archway_predictions(
        repo_name="demo",
        untyped_root=source_root,
        predictions_root=tmp_path / "predictions",
        engine_worktree=engine,
        runner=(sys.executable,),
        timeout=30,
        per_file_timeout=5,
        trace_jsonl=trace_jsonl,
    )

    records = [json.loads(line) for line in trace_jsonl.read_text().splitlines()]
    by_slot = {record["slot"]: record for record in records}
    assert by_slot["param:argv"]["insertion_happened"] is False
    assert by_slot["param:argv"]["insertion_reason"] == "no inferred parameter candidate"
    assert by_slot["param:argv"]["fallback_reason"] == "no inferred parameter candidate"
    assert by_slot["return"]["insertion_reason"] == "no inferred return candidate"


def test_emit_predictions_profile_jsonl_records_per_file_timings(tmp_path) -> None:
    engine = tmp_path / "engine"
    sd_core = engine / "sd_core"
    runners = sd_core / "runners"
    runners.mkdir(parents=True)
    (sd_core / "__init__.py").write_text("", encoding="utf-8")
    (runners / "__init__.py").write_text("", encoding="utf-8")
    (runners / "analysis_observability.py").write_text(
        """
class AnalysisObservationConfig:
    def __init__(self, mode="summary"):
        self.mode = mode

    @classmethod
    def summary(cls):
        return cls("summary")

    @classmethod
    def diagnostic(cls):
        return cls("diagnostic")

    @classmethod
    def off(cls):
        return cls("off")
""",
        encoding="utf-8",
    )
    (runners / "file_results.py").write_text(
        """
class _Run:
    finalized = object()

class _Result:
    status = "analyzed"
    run = _Run()

    def to_jsonable(self):
        return {
            "analysis_summary": {
                "schema": "archway.analysis_run_summary.v1",
                "phases": [
                    {"name": "types.evaluate", "wall_seconds": 0.125, "status": "ok"}
                ],
                "type_functor": {
                    "body_execution_hotspots": [
                        {"body_name": "f", "execution_count": 1, "wall_seconds": 0.1}
                    ]
                },
            }
        }

class FileAnalysisFailure(Exception):
    pass

def analyze_source_file_result(
    source,
    module,
    repo_path=None,
    observation_config=None,
    body_summary_consumption="off",
    analysis_product="standalone",
):
    if body_summary_consumption != "safe":
        raise RuntimeError(f"policy was {body_summary_consumption}")
    if analysis_product != "type_body_summary_product":
        raise RuntimeError(f"product was {analysis_product}")
    if getattr(observation_config, "mode", None) != "diagnostic":
        raise RuntimeError(f"observation was {getattr(observation_config, 'mode', None)}")
    if "boom" in source:
        raise RuntimeError("synthetic")
    return _Result()
""",
        encoding="utf-8",
    )
    (sd_core / "analysis_server.py").write_text(
        """
def _analysis():
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

def _encode_finalized(finalized):
    return _analysis()

def analyze_source(source, module_name):
    if "boom" in source:
        raise RuntimeError("synthetic")
    return _analysis()
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
        body_summary_consumption="safe",
        analysis_product="type_body_summary_product",
        analysis_observation_mode="diagnostic",
    )

    rows = [json.loads(line) for line in profile_jsonl.read_text(encoding="utf-8").splitlines()]
    by_file = {row["file"]: row for row in rows}
    assert stats.file_profiles
    assert by_file["ok.py"]["status"] == "ok"
    assert by_file["ok.py"]["seconds_engine_probe"] >= 0
    assert by_file["ok.py"]["functions_seen"] == 1
    assert by_file["ok.py"]["analysis_summary"]["schema"] == (
        "archway.analysis_run_summary.v1"
    )
    assert by_file["ok.py"]["analysis_summary"]["type_functor"][
        "body_execution_hotspots"
    ][0]["body_name"] == "f"
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


def test_capture_runtime_phase_profile_file_splits_translation_from_analysis(tmp_path) -> None:
    engine = tmp_path / "engine"
    sd_core = engine / "sd_core"
    tooling = sd_core / "tooling"
    tooling.mkdir(parents=True)
    (sd_core / "__init__.py").write_text("", encoding="utf-8")
    (tooling / "__init__.py").write_text("", encoding="utf-8")
    (tooling / "harness.py").write_text(
        """
class TranslationResult:
    def __init__(self, trace=False):
        self.morphism = object()
        self.traces = [type("Trace", (), {"spans": [1, 2, 3]})()] if trace else []

    @classmethod
    def from_source(cls, source, trace=False, name=None):
        return cls(trace=trace)
""",
        encoding="utf-8",
    )
    (sd_core / "analysis_server.py").write_text(
        """
import time

def analyze_source(source, module_name):
    if "slow" in source:
        time.sleep(5)
    return {"functions": [{"name": "f"}]}
""",
        encoding="utf-8",
    )
    source = tmp_path / "demo.py"
    source.write_text("slow = True\n", encoding="utf-8")

    profile = capture_runtime_phase_profile_file(
        engine_worktree=engine,
        source_path=source,
        module_name="demo",
        runner=(sys.executable,),
        timeout=1,
    )

    assert profile["file"] == str(source)
    assert profile["import_only"]["ok"] is True
    assert profile["translation_no_trace"]["ok"] is True
    assert profile["translation_trace"]["ok"] is True
    assert profile["translation_trace"]["span_count"] == 3
    assert profile["analyze_source"]["ok"] is False
    assert "TimeoutExpired" in profile["analyze_source"]["error"]
