import json
import subprocess
from pathlib import Path

from archway_benchmarks.typybench_residual_audit import (
    audit_rows,
    run_official_residual_probe,
)


def test_audit_rows_preserves_evidence_and_groups_actionable_classes() -> None:
    result = audit_rows([
        {
            "key": "pkg.f@value", "expected": "builtins.str",
            "predicted": "Any", "similarity": 0.0, "exact": 0,
            "missing": False,
        },
        {
            "key": "pkg.f::return", "expected": "builtins.list[builtins.str]",
            "predicted": "builtins.list[Any]", "similarity": 0.5,
            "exact": 0, "missing": False,
        },
        {
            "key": "pkg.g::return", "expected": "builtins.int",
            "predicted": None, "similarity": 0.0, "exact": 0,
            "missing": True,
        },
        {
            "key": "pkg.C.attr", "expected": "builtins.bool",
            "predicted": "builtins.bool", "similarity": 1.0, "exact": 1,
            "missing": False,
        },
    ])

    assert result["class_counts"] == {
        "erased_type_arguments": 1,
        "exact": 1,
        "missing": 1,
        "unconstrained_any": 1,
    }
    assert result["kind_class_counts"]["parameter:unconstrained_any"] == 1
    assert result["kind_class_counts"]["return:erased_type_arguments"] == 1
    assert result["rows"][0]["expected"] == "builtins.str"


def test_official_probe_uses_one_repo_prediction_root(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions"
    (predictions / "demo").mkdir(parents=True)
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        payload = {"rows": [{
            "key": "demo.f::return", "expected": "builtins.int",
            "predicted": "builtins.int", "similarity": 1.0,
            "exact": 1, "missing": False,
        }]}
        return subprocess.CompletedProcess(
            command, 0,
            "noise\nARCHWAY_TYPYBENCH_RESIDUALS " + json.dumps(payload) + "\n",
            "",
        )

    result = run_official_residual_probe(
        repo_name="demo", predictions_root=predictions, runner=runner,
    )

    assert result["class_counts"] == {"exact": 1}
    assert captured["command"][0:2] == ["docker", "run"]
    assert "typybench-demo" in captured["command"]
    assert any(str(predictions.resolve()) in item for item in captured["command"])
