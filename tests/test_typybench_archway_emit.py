import ast
import inspect
import json
import sys

import archway_benchmarks.typybench_archway_emit as emit_module
from archway_benchmarks.typybench_archway_emit import (
    _annotate_source,
    _probe_progress,
    _run_engine_probe,
    _run_successor_repo_probe,
    _successor_function_types,
    _scored_slot_accounting,
    _successor_variable_types,
    capture_runtime_phase_profile_file,
    capture_translation_trace_file,
    emit_archway_predictions,
)


def test_successor_probe_requires_authoritative_signature_workload_api() -> None:
    worker_source = inspect.getsource(_run_successor_repo_probe)

    assert 'session, "signature_workload_roots", None' in worker_source
    assert 'getattr(session, "run_workload", None)' in worker_source
    assert "signature-body-root-projection" in worker_source
    assert "plan_signature_workload" in worker_source
    assert "targeted_body_providers" not in worker_source
    assert "observation_workload_roots" not in worker_source
    assert "exact-address-deduplication" not in worker_source


def test_probe_progress_retains_compact_timeout_evidence() -> None:
    progress = _probe_progress(
        "ARCHWAY_PHASE translation 8.125000\n"
        "ARCHWAY_PHASE signature_demands 3901\n"
        "ARCHWAY_PHASE body_roots 1105\n"
        "ARCHWAY_TRANSLATION_START pkg/slow.py\n"
        "ARCHWAY_TRANSLATION_DONE 1.500000 ok pkg/slow.py\n"
        "ARCHWAY_TRANSLATION_START pkg/active.py\n"
        'ARCHWAY_BODY_PLAN [["first","second"]]\n'
        "ARCHWAY_BODY_START 2/139 appworld.api_docs:generate_example "
        "fact-address:v1:active\n"
        "ARCHWAY_BODY 2/139 16.250000 exec=618 topology=5940 "
        "appworld.api_docs:generate_example\n"
        "ARCHWAY_BODY_START 3/139 appworld.api_docs:next "
        "fact-address:v1:next\n"
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
        "active_body": {
            "index": 3,
            "total": 139,
            "label": "appworld.api_docs:next",
            "root_id": "fact-address:v1:next",
        },
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
        "f": {"params": {"x": "int"}, "return": "str"}
    }


def test_successor_requirement_candidates_fill_unknown_parameter_only() -> None:
    observations = [
        {
            "line": 4, "name": "x", "kind": "parameter",
            "function": "f", "family": "TypeOf", "types": [],
        },
        {
            "line": 4, "name": "x", "kind": "parameter",
            "function": "f", "family": "AnnotationCandidatesAt",
            "types": ["builtins.str"],
        },
    ]

    assert _successor_function_types(observations) == {
        "f": {"params": {"x": "str"}, "return": None}
    }


def test_successor_observed_type_composes_with_supported_candidates() -> None:
    observations = [
        {
            "line": 4, "name": "x", "kind": "parameter",
            "function": "f", "family": "TypeOf",
            "types": ["builtins.bytes"],
        },
        {
            "line": 4, "name": "x", "kind": "parameter",
            "function": "f", "family": "AnnotationCandidatesAt",
            "types": ["builtins.str"],
        },
    ]

    assert _successor_function_types(observations) == {
        "f": {"params": {"x": "Union[bytes, str]"}, "return": None}
    }


def test_successor_generic_shape_refines_nominal_container_type() -> None:
    observations = [
        {
            "line": 4, "name": "f", "kind": "return",
            "function": None, "family": "TypeOf",
            "types": ["builtins.list"],
        },
        {
            "line": 4, "name": "f", "kind": "return",
            "function": None, "family": "GenericShapeOf",
            "shape": {
                "kind": "generic_shape_set",
                "unknown": False,
                "shapes": [{
                    "constructor": "builtins.list",
                    "open": False,
                    "positions": [{
                        "position": "summary:*",
                        "value": {
                            "nominal_types": ["builtins.str"],
                            "nested": {
                                "kind": "generic_shape_set",
                                "unknown": False,
                                "shapes": [],
                            },
                        },
                    }],
                }],
            },
        },
    ]

    assert _successor_function_types(observations) == {
        "f": {"params": {}, "return": "list[str]"}
    }


def test_successor_generator_shape_renders_yield_type() -> None:
    observations = [{
        "line": 4, "name": "values", "kind": "return",
        "function": None, "family": "GenericShapeOf",
        "shape": {
            "kind": "generic_shape_set",
            "unknown": False,
            "shapes": [{
                "constructor": "builtins.generator",
                "open": False,
                "positions": [{
                    "position": "yield:*",
                    "value": {
                        "nominal_types": ["builtins.int"],
                        "nested": {
                            "kind": "generic_shape_set",
                            "unknown": False,
                            "shapes": [],
                        },
                    },
                }],
            }],
        },
    }]

    assert _successor_function_types(observations) == {
        "values": {
            "params": {}, "return": "Generator[int, None, None]",
        }
    }


def test_successor_generic_shape_renders_nested_mapping_value() -> None:
    observations = [{
        "line": 4, "name": "payload", "kind": "return",
        "function": None, "family": "GenericShapeOf",
        "shape": {
            "kind": "generic_shape_set",
            "unknown": False,
            "shapes": [{
                "constructor": "builtins.dict",
                "open": False,
                "positions": [{
                    "position": "builtins.str:'items'",
                    "value": {
                        "nominal_types": ["builtins.list"],
                        "nested": {
                            "kind": "generic_shape_set",
                            "unknown": False,
                            "shapes": [{
                                "constructor": "builtins.list",
                                "open": False,
                                "positions": [{
                                    "position": "builtins.int:0",
                                    "value": {
                                        "nominal_types": ["builtins.str"],
                                        "nested": {
                                            "kind": "generic_shape_set",
                                            "unknown": False,
                                            "shapes": [],
                                        },
                                    },
                                }],
                            }],
                        },
                    },
                }],
            }],
        },
    }]

    assert _successor_function_types(observations) == {
        "payload": {
            "params": {}, "return": "dict[str, list[str]]",
        }
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
        "Environment.__init__": {
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


def test_successor_observations_use_definition_identity_for_multiline_method() -> None:
    observations = [{
        "line": 6,
        "definition_line": 2,
        "name": "value",
        "kind": "parameter",
        "function": "Model.convert",
        "body_morphism_id": "sid:v1:box:body",
        "types": ["builtins.str"],
    }]

    function_types = _successor_function_types(observations)
    annotated, stats = _annotate_source(
        "class Model:\n"
        "    def convert(\n"
        "        self,\n"
        "        value,\n"
        "    ):\n"
        "        return value\n",
        function_types,
    )

    assert "value: str" in annotated
    assert stats["params"] == 1


def test_scored_slot_accounting_separates_unresolved_and_identity_gaps() -> None:
    source = (
        "def mapped(value):\n"
        "    return value\n"
        "\n"
        "def absent(flag):\n"
        "    return flag\n"
    )
    observations = [
        {
            "line": 1,
            "definition_line": 1,
            "name": "value",
            "kind": "parameter",
            "function": "mapped",
            "types": ["builtins.str"],
        },
        {
            "line": 1,
            "definition_line": 1,
            "name": "mapped",
            "kind": "return",
            "function": None,
            "types": [],
        },
        {
            "line": 99,
            "definition_line": 99,
            "name": "ghost",
            "kind": "return",
            "function": None,
            "types": ["builtins.int"],
        },
    ]
    function_types = _successor_function_types(observations)

    accounting = _scored_slot_accounting(
        source, observations, function_types, emitted_params=1,
    )

    assert accounting == {
        "manifest_slots": 4,
        "engine_cataloged_slots": 2,
        "resolved_candidates": 1,
        "resolved_emitted": 1,
        "resolved_preserved": 0,
        "resolved_unrenderable": 0,
        "resolved_not_emitted": 0,
        "unresolved_facts": 1,
        "uncataloged_engine_identity": 2,
        "orphan_engine_observations": 1,
    }


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


def test_repository_emission_demands_only_direct_scorer_signature_slots(
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
    requested_kinds = []

    def probe(**kwargs):
        requested_kinds.append(kwargs["observation_kinds"])
        return record

    monkeypatch.setattr(emit_module, "_run_successor_repo_probe", probe)

    default_root = tmp_path / "default"
    default = emit_archway_predictions(
        repo_name="demo",
        untyped_root=source_root,
        predictions_root=default_root,
        engine_worktree=engine,
    )
    assert (default_root / "demo" / "demo.py").read_text() == "value = 1\n"
    assert default.variables_annotated == 0
    assert requested_kinds == [frozenset(("parameter", "return"))]


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
                "kind": "class_field",
                "family": "ClassAttributeTypeOf",
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


def test_class_field_emission_rejects_ordinary_class_attributes() -> None:
    observations = [{
        "line": 2,
        "name": "Model.cache",
        "kind": "variable",
        "family": "ClassAttributeTypeOf",
        "function": None,
        "types": ["builtins.dict"],
    }]

    assert _successor_variable_types(
        observations, class_fields_only=True
    ) == {}


def test_class_field_emission_accepts_only_reviewed_transform_projection() -> None:
    observations = [{
        "line": 2,
        "name": "Model.value",
        "kind": "class_field",
        "family": "ClassAttributeTypeOf",
        "function": None,
        "types": ["builtins.int"],
    }]

    assert _successor_variable_types(
        observations, class_fields_only=True
    ) == {(2, "value"): "int"}


def test_annotate_source_inserts_params_returns_and_typing_import() -> None:
    source = '''"""module docstring"""

def f(x, y=1):
    return x

async def g(items, **kwargs):
    return items
'''
    function_types = {
        "f": {"params": {"x": "int", "y": "Union[int, str]"}, "return": "Any"},
        "g": {
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


def test_annotate_source_uses_existing_import_spelling_for_semantic_types() -> None:
    source = (
        "from paperqa.types import DocDetails\n"
        "from paperqa import settings as config\n\n"
        "def select(item):\n"
        "    return item\n"
    )
    function_types = {
        "select": {
            "params": {
                "item": "list[paperqa.types.DocDetails]",
            },
            "return": "paperqa.settings.Settings",
        },
    }

    annotated, _stats = _annotate_source(source, function_types)

    ast.parse(annotated)
    assert "def select(item: list[DocDetails]) -> config.Settings:" in annotated


def test_annotate_source_preserves_existing_annotations() -> None:
    source = "def f(x: str) -> str:\n    return x\n"
    function_types = {"f": {"params": {"x": "int"}, "return": "int"}}

    annotated, stats = _annotate_source(source, function_types)

    assert "def f(x: str) -> str:" in annotated
    assert stats == {"functions": 0, "params": 0, "returns": 0, "variables": 0}


def test_annotate_source_places_typing_import_after_future_imports() -> None:
    source = '''"""module docstring"""
from __future__ import annotations

def f(x):
    return x
'''
    function_types = {"f": {"params": {"x": "Any"}, "return": "Any"}}

    annotated, stats = _annotate_source(source, function_types)

    ast.parse(annotated)
    future_at = annotated.index("from __future__ import annotations")
    typing_at = annotated.index("from typing import Any, Union")
    assert future_at < typing_at
    assert stats == {"functions": 1, "params": 1, "returns": 1, "variables": 0}


def test_emit_predictions_leaves_original_source_on_invalid_annotation_syntax(
    monkeypatch, tmp_path,
) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    monkeypatch.setattr(
        emit_module,
        "_run_successor_repo_probe",
        lambda **_kwargs: {
            "ok": True,
            "files": {"demo.py": [
                {
                    "line": 1, "name": "x", "kind": "parameter",
                    "function": "f", "types": ["list["],
                },
                {
                    "line": 1, "name": "f", "kind": "return",
                    "function": None, "types": ["builtins.int"],
                },
            ]},
            "analysis_summary": {"translation_failures": {}},
        },
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


def test_emit_predictions_preserves_cookiecutter_template_paths(
    monkeypatch, tmp_path,
) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()

    source_root = tmp_path / "repo_without_types"
    template_dir = source_root / "taipy" / "templates" / "default" / "{{cookiecutter.__root_folder}}"
    template_dir.mkdir(parents=True)
    source = template_dir / "{{cookiecutter.__main_file}}.py"
    source.write_text('MARKER = "{{cookiecutter.__root_folder}}"\n', encoding="utf-8")

    rel = "taipy/templates/default/{{cookiecutter.__root_folder}}/{{cookiecutter.__main_file}}.py"

    def probe(**kwargs):
        assert kwargs["source_root"] == source_root
        assert "{{cookiecutter.__root_folder}}" in source.read_text()
        return {
            "ok": True,
            "files": {rel: []},
            "analysis_summary": {"translation_failures": {}},
        }

    monkeypatch.setattr(emit_module, "_run_successor_repo_probe", probe)

    stats = emit_archway_predictions(
        repo_name="taipy",
        untyped_root=source_root,
        predictions_root=tmp_path / "predictions",
        engine_worktree=engine,
        runner=(sys.executable,),
        timeout=30,
        per_file_timeout=5,
    )

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


def test_emit_predictions_retains_repository_timeout_evidence(
    tmp_path, monkeypatch
) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    source_root = tmp_path / "repo"
    source_root.mkdir()
    (source_root / "demo.py").write_text("def f(x):\n    return x\n")
    progress = {
        "phase_progress": {"forward": 12.5, "body_roots": 40},
        "body_profiles": [{"index": 3, "total": 8}],
    }
    monkeypatch.setattr(
        emit_module,
        "_run_successor_repo_probe",
        lambda **_kwargs: {
            "ok": False,
            "error": "TimeoutExpired: analysis exceeded 30s",
            "trace_tail": "ARCHWAY_BODY 3/8",
            "analysis_summary": progress,
        },
    )

    stats = emit_archway_predictions(
        repo_name="demo",
        untyped_root=source_root,
        predictions_root=tmp_path / "predictions",
        engine_worktree=engine,
        timeout=30,
    )

    assert stats.files_analyzed == 0
    assert stats.probe_error == "TimeoutExpired: analysis exceeded 30s"
    assert stats.probe_trace_tail == "ARCHWAY_BODY 3/8"
    assert stats.analysis_summary == progress
    assert stats.file_profiles[0].status == "engine_failed"
    assert stats.file_profiles[0].analysis_summary == progress


def test_emit_predictions_trace_jsonl_records_raw_rendered_and_insertion(
    monkeypatch, tmp_path,
) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    monkeypatch.setattr(
        emit_module,
        "_run_successor_repo_probe",
        lambda **_kwargs: {
            "ok": True,
            "files": {"demo.py": [
                {
                    "line": 1, "name": "x", "kind": "parameter",
                    "function": "f", "types": ["builtins.int"],
                },
                {
                    "line": 1, "name": "y", "kind": "parameter",
                    "function": "f", "types": ["list[Any]"],
                },
                {
                    "line": 1, "name": "z", "kind": "parameter",
                    "function": "f", "types": ["builtins.str"],
                },
                {
                    "line": 1, "name": "f", "kind": "return",
                    "function": None, "types": ["Any"],
                },
            ]},
            "analysis_summary": {"translation_failures": {}},
        },
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
    assert by_slot["param:x"]["raw_candidates"] == [
        {"successor_types": ["int"]}
    ]
    assert by_slot["param:x"]["rendered_annotation"] == "int"
    assert by_slot["param:x"]["insertion_happened"] is True
    assert by_slot["param:x"]["final_annotation"] == "int"
    assert by_slot["param:y"]["rendered_annotation"] == "list[Any]"
    assert by_slot["param:y"]["insertion_happened"] is False
    assert by_slot["param:y"]["insertion_reason"] == "existing annotation preserved"
    assert by_slot["param:y"]["fallback_reason"] is None
    assert by_slot["param:z"]["insertion_reason"] == "parameter not present in AST"
    assert by_slot["return"]["rendered_annotation"] == "Any"
    assert by_slot["return"]["fallback_reason"] is None
    assert by_slot["return"]["final_annotation"] == "bool"


def test_emit_trace_records_slots_omitted_by_engine_projection(
    monkeypatch, tmp_path,
) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    monkeypatch.setattr(
        emit_module,
        "_run_successor_repo_probe",
        lambda **_kwargs: {
            "ok": True,
            "files": {"demo.py": [
                {
                    "line": 1, "name": "argv", "kind": "parameter",
                    "function": "main", "types": [],
                },
                {
                    "line": 1, "name": "main", "kind": "return",
                    "function": None, "types": [],
                },
            ]},
            "analysis_summary": {"translation_failures": {}},
        },
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


def test_emit_predictions_profile_jsonl_records_per_file_timings(
    monkeypatch, tmp_path,
) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    analysis_summary = {
        "schema": "archway.analysis_run_summary.v1",
        "type_functor": {
            "body_execution_hotspots": [
                {"body_name": "f", "execution_count": 1,
                 "wall_seconds": 0.1}
            ],
        },
        "translation_failures": {"bad.py": "RuntimeError: synthetic"},
    }
    monkeypatch.setattr(
        emit_module,
        "_run_successor_repo_probe",
        lambda **_kwargs: {
            "ok": True,
            "files": {"ok.py": [
                {
                    "line": 1, "name": "x", "kind": "parameter",
                    "function": "f", "types": ["builtins.int"],
                },
                {
                    "line": 1, "name": "f", "kind": "return",
                    "function": None, "types": ["builtins.int"],
                },
            ], "bad.py": []},
            "analysis_summary": analysis_summary,
        },
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
    assert by_file["bad.py"]["status"] == "translation_failed"
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
