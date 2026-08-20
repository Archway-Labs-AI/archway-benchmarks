import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

from archway_benchmarks.types import Annotation, Location, Snippet


def _checkpoint_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "typeevalpy_successor_checkpoint.py"
    )
    spec = importlib.util.spec_from_file_location(
        "typeevalpy_successor_checkpoint", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checkpoint_predictions_finalize_detailed_public_run(tmp_path):
    module = _checkpoint_module()
    location = Location("main.py", 1, 1, "variable", "value")
    snippet = Snippet(
        benchmark="typeevalpy_autogen",
        suite_path="python_features/authored/checkpoint",
        file_path="main.py",
        source="value = 1\n",
        annotations=(Annotation(location, frozenset(("int",))),),
    )
    records = {
        snippet.suite_path: {
            "prediction_records": [{
                "file": "main.py",
                "line": 1,
                "col": 1,
                "kind": "variable",
                "name": "value",
                "function": None,
                "types": ["int"],
            }],
        }
    }
    benchmark = type("Benchmark", (), {"name": "typeevalpy_autogen"})()
    db_path = tmp_path / "runs.db"

    run_id = module._persist_run(
        benchmark=benchmark,
        snippets=(snippet,),
        records=records,
        db_path=db_path,
        notes="checkpoint test",
        metadata={"analysis_surface": "diagram-only"},
    )

    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute(
            "select exact_total from scores where run_id=? and scope='all'",
            (run_id,),
        ).fetchone() == (1,)
        assert connection.execute(
            "select outcome from annotations where run_id=?", (run_id,)
        ).fetchone() == ("EXACT",)
    finally:
        connection.close()

    summary_path = tmp_path / "checkpoint.summary.json"
    summary_path.write_text(json.dumps({
        "db_path": str(db_path.resolve()),
        "local_run_id": run_id,
    }))
    assert module._completed_run_id(summary_path, db_path.resolve()) == run_id


def test_checkpoint_refuses_empty_corpus(tmp_path):
    module = _checkpoint_module()

    with pytest.raises(RuntimeError, match="no recognized snippets"):
        module._require_nonempty_corpus([], tmp_path)


def test_checkpoint_resume_retries_failed_snippet(tmp_path):
    module = _checkpoint_module()
    checkpoint = tmp_path / "checkpoint.jsonl"
    checkpoint.write_text(
        json.dumps({"kind": "header", "schema_version": 2}) + "\n"
        + json.dumps({
            "kind": "snippet",
            "suite_path": "python_features/authored/retry",
            "error": "ModuleNotFoundError: missing dependency",
        }) + "\n"
    )

    header, records = module._load_records(checkpoint)

    assert header == {"kind": "header", "schema_version": 2}
    assert records == {}
