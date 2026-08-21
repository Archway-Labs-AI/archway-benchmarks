from __future__ import annotations

import json

from archway_benchmarks import bugsinpy_detector
from archway_benchmarks.bugsinpy_detector import ExceptionFindingEvidence
from archway_benchmarks.bugsinpy_protocol import DetectorInputManifest


def _manifest(root):
    return DetectorInputManifest(
        protocol="repository-static-v1",
        bug_key="demo-1",
        project="demo",
        buggy_revision="a" * 40,
        repository_root=str(root),
    )


def test_detector_scans_whole_repository_and_reports_failures_as_coverage(tmp_path, monkeypatch):
    (tmp_path / "good.py").write_text("x = 1 / 0\n")
    (tmp_path / "bad.py").write_text("not python for fixture\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("x = 1 / 0\n")

    def analyze(source, path):
        if path == "bad.py":
            raise SyntaxError("fixture")
        return (ExceptionFindingEvidence(path, 1, 1, ("ZeroDivisionError",), "binop:div"),)

    monkeypatch.setattr(bugsinpy_detector, "_analyze_file_with_timeout", analyze)
    prediction = bugsinpy_detector.detect(_manifest(tmp_path))

    assert prediction.repository_files == 2
    assert prediction.analyzed_files == 1
    assert prediction.findings[0].file == "good.py"
    assert prediction.findings[0].evidence[0]["origin"] == "semantic_runtime"


def test_protected_operation_filter_suppresses_try_body():
    tree = bugsinpy_detector.ast.parse(
        "try:\n    value = 1 / 0\nexcept (ValueError, ZeroDivisionError):\n    value = None\n"
    )
    assert bugsinpy_detector._guarded_by_enclosing_try(tree, 2)
    assert not bugsinpy_detector._guarded_by_enclosing_try(tree, 4)


def test_cli_writes_bound_prediction(tmp_path, monkeypatch):
    (tmp_path / "only.py").write_text("x = 1\n")
    manifest_path = tmp_path / "manifest.json"
    output_path = tmp_path / "prediction.json"
    manifest_path.write_text(json.dumps(_manifest(tmp_path).to_json()))
    monkeypatch.setattr(
        bugsinpy_detector, "_analyze_file_with_timeout", lambda source, path: ()
    )

    assert bugsinpy_detector.main([str(manifest_path), str(output_path)]) == 0
    output = json.loads(output_path.read_text())
    assert output["bug_key"] == "demo-1"
    assert output["coverage"]["analyzed_files"] == 1
