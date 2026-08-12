from __future__ import annotations

import pytest

from archway_benchmarks.pycg_residual_audit import audit_run, residual_id


def _record(edge: list[str], line: str) -> dict:
    return {
        "projected_edge": edge,
        "semantic_edge": edge,
        "callsite_morphism_id": "sid:v1:box:call",
        "source_module": "pkg.main",
        "source_position": {"line": 4, "column": 4},
        "source_line": line,
        "target_kind": "CallableBoundary",
        "evidence_grade": "semantic",
    }


def _run() -> dict:
    return {
        "suite": "macro",
        "score": {
            "true_positive": 1,
            "false_positive": 1,
            "false_negative": 2,
        },
        "cases": [{
            "suite_path": "sample",
            "status": "ok",
            "predicted_edges": [
                ["pkg.main.f", "pkg.main.expected"],
                ["pkg.main.f", "pkg.main.extra"],
            ],
            "extra_edges": [["pkg.main.f", "pkg.main.extra"]],
            "missing_edges": [
                ["pkg.main.f", "pkg.main.target"],
                ["pkg.absent", "pkg.absent.target"],
            ],
            "analysis_evidence": {
                "semantic_call_edge_evidence": [
                    _record(["pkg.main.f", "pkg.main.extra"], "target()")
                ],
                "pycg_projection_lineage": [],
            },
        }],
    }


def test_residual_audit_preserves_raw_score_and_inventories_both_sides() -> None:
    result = audit_run(_run())

    assert result["raw_score"] == _run()["score"]
    assert result["kind_counts"] == {
        "false_negative": 2,
        "false_positive": 1,
    }
    assert result["review_disposition_counts"] == {"pending": 3}
    assert result["unique_residual_count"] == 3
    assert result["scored_residual_occurrence_count"] == 3
    assert result["duplicate_expected_occurrence_count"] == 0
    residuals = result["cases"][0]["residuals"]
    lexical = next(
        item for item in residuals
        if item["edge"] == ["pkg.main.f", "pkg.main.target"]
    )
    assert lexical["automated_cluster"] == (
        "wrong_or_missing_target_at_observed_callsite"
    )
    absent = next(item for item in residuals if item["edge"][0] == "pkg.absent")
    assert absent["automated_cluster"] == "missing_caller_analysis"


def test_review_manifest_is_separate_validated_and_stable() -> None:
    identity = residual_id(
        "sample", "false_positive", ("pkg.main.f", "pkg.main.extra")
    )
    manifest = {
        "schema": "archway.pycg.residual-adjudications.v1",
        "entries": [{
            "residual_id": identity,
            "disposition": "semantically_valid_extra",
            "reviewer": "reviewer@example",
            "rationale": "The retained source callsite invokes extra directly.",
            "evidence_refs": ["sid:v1:box:call"],
        }],
    }

    result = audit_run(_run(), adjudication_manifest=manifest)
    assert result["review_disposition_counts"] == {
        "pending": 2,
        "semantically_valid_extra": 1,
    }


def test_review_manifest_rejects_stale_or_unsubstantiated_entries() -> None:
    identity = residual_id(
        "sample", "false_positive", ("pkg.main.f", "pkg.main.extra")
    )
    with pytest.raises(ValueError, match="lacks rationale"):
        audit_run(_run(), adjudication_manifest={
            "schema": "archway.pycg.residual-adjudications.v1",
            "entries": [{
                "residual_id": identity,
                "disposition": "archway_unsoundness",
                "reviewer": "reviewer@example",
                "rationale": "",
                "evidence_refs": ["trace:1"],
            }],
        })
