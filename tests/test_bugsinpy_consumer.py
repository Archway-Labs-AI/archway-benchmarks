"""Bottom-only BugsInPy FindingCandidate consumer tests."""
from __future__ import annotations

import json

from archway_benchmarks.bugsinpy_consumer import consume_bottom_findings


def _manifest() -> list[dict]:
    return [
        {
            "key": "demoproj:1",
            "project": "demoproj",
            "files": [{"repo_path": "demoproj/core.py", "fetch_status": "ok"}],
        }
    ]


def test_consumer_emits_strict_flags_only_for_strict_position_basis():
    results = {
        "demoproj:1": {
            "demoproj/core.py": {
                "status": "analyzed",
                "bottom_rows": [
                    11,
                    {"line": 12, "source_position_basis": "defining-expr"},
                    {"line": 9, "source_position_basis": "enclosing-function"},
                    {"source_position_basis": "rowless", "wire_cid": "cid-rowless"},
                ],
                "n_bottom": 5,
            },
            "tests/utils.py": {
                "status": "analyzed",
                "bottom_rows": [11],
                "n_bottom": 1,
            },
        }
    }

    out = consume_bottom_findings(_manifest(), results)

    assert out.flags_strict == {
        "demoproj:1": [{"file": "demoproj/core.py", "lines": [11, 12]}]
    }
    diagnostic = out.candidates_diagnostic
    assert diagnostic["summary"]["total_candidates"] == 6
    assert diagnostic["summary"]["strict_eligible_candidates"] == 2
    assert diagnostic["summary"]["classification_counts"] == {
        "enclosing-function-fallback": 1,
        "rowless": 2,
        "strict-eligible": 2,
        "wrong-file": 1,
    }
    by_class = {
        (c["provenance_classification"], c["file"], c["line"])
        for c in diagnostic["candidates"]
    }
    assert ("wrong-file", "tests/utils.py", 11) in by_class
    assert ("rowless", "demoproj/core.py", None) in by_class
    assert ("enclosing-function-fallback", "demoproj/core.py", 9) in by_class


def test_legacy_build_flags_uses_strict_consumer_rules():
    from archway_benchmarks.bugsinpy_flagger import build_flags

    results = {
        "demoproj:1": {
            "demoproj/core.py": {
                "status": "analyzed",
                "bottom_rows": [
                    {"line": 11, "source_position_basis": "direct-node"},
                    {"line": 12, "source_position_basis": "enclosing-function"},
                ],
                "n_bottom": 3,
            },
            "tests/utils.py": {
                "status": "analyzed",
                "bottom_rows": [11],
                "n_bottom": 1,
            },
        }
    }

    flags, status = build_flags(_manifest(), results)

    assert flags == {"demoproj:1": [{"file": "demoproj/core.py", "lines": [11]}]}
    assert status["bugs_flagged_any"] == 1
    assert status["candidate_classification_counts"]["rowless"] == 1
    assert status["candidate_classification_counts"]["wrong-file"] == 1


def test_consumer_cli_writes_strict_and_diagnostic_outputs(tmp_path):
    from archway_benchmarks.cli import main

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest()))
    results = tmp_path / "results.json"
    results.write_text(json.dumps({
        "demoproj:1": {
            "demoproj/core.py": {
                "status": "analyzed",
                "bottom_rows": [11, {"line": 8, "source_position_basis": "enclosing-function"}],
                "n_bottom": 2,
            }
        }
    }))
    flags = tmp_path / "flags.strict.json"
    candidates = tmp_path / "candidates.diagnostic.json"
    status = tmp_path / "consumer_status.json"

    rv = main([
        "bugsinpy-consume-findings",
        "--manifest", str(manifest),
        "--results", str(results),
        "--out-flags", str(flags),
        "--out-candidates", str(candidates),
        "--out-status", str(status),
    ])

    assert rv == 0
    assert json.loads(flags.read_text()) == {
        "demoproj:1": [{"file": "demoproj/core.py", "lines": [11]}]
    }
    diagnostic = json.loads(candidates.read_text())
    assert diagnostic["summary"]["classification_counts"] == {
        "enclosing-function-fallback": 1,
        "strict-eligible": 1,
    }
