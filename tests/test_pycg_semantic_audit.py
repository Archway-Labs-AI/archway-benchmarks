from __future__ import annotations

from archway_benchmarks.pycg_semantic_audit import audit_run, audit_runs


def _record(edge: list[str], line: str, target_kind: str = "CallableBoundary") -> dict:
    return {
        "projected_edge": edge,
        "callsite_morphism_id": "sid:v1:box:1",
        "source_module": "pkg.main",
        "source_position": {"line": 2, "column": 4},
        "source_line": line,
        "target_kind": target_kind,
        "evidence_grade": "semantic",
        "invocation_kind": "CallableInvocationTarget",
    }


def test_audit_preserves_raw_score_and_requires_adjudication() -> None:
    run = {
        "suite": "macro",
        "score": {"precision": 0.5},
        "cases": [
            {
                "suite_path": "sample",
                "status": "ok",
                "extra_edges": [
                    ["pkg.main", "pkg.main.target"],
                    ["pkg.main", "pkg.resource.__enter__"],
                    ["pkg.main", "external.Client.send"],
                ],
                "analysis_evidence": {
                    "semantic_call_edge_evidence": [
                        _record(["pkg.main", "pkg.main.target"], "target()"),
                        _record(
                            ["pkg.main", "pkg.resource.__enter__"],
                            "with resource:",
                        ),
                        _record(
                            ["pkg.main", "external.Client.send"],
                            "client()",
                            "ExternalDependencyBoundary",
                        ),
                    ],
                    "pycg_projection_lineage": [],
                },
            }
        ],
    }

    audit = audit_run(run)

    assert audit["raw_score"] == {"precision": 0.5}
    assert audit["raw_extra_count"] == 3
    assert audit["evidence_status_counts"] == {"contextual_semantic_evidence": 3}
    assert audit["source_relationship_counts"] == {
        "callee_lexeme_visible": 1,
        "diagram_resolved_indirectly": 1,
        "syntax_implied_protocol": 1,
    }
    assert audit["semantic_category_counts"] == {
        "external_dependency_call": 1,
        "implicit_protocol_call": 1,
        "project_or_resolved_object_call": 1,
    }
    assert all(
        edge["disposition"] == "review_required"
        for edge in audit["cases"][0]["edges"]
    )


def test_audit_distinguishes_lineage_only_and_missing_evidence() -> None:
    run = {
        "suite": "macro",
        "score": {},
        "cases": [
            {
                "suite_path": "sample",
                "status": "ok",
                "extra_edges": [["main", "main.a"], ["main", "main.b"]],
                "analysis_evidence": {
                    "semantic_call_edge_evidence": [],
                    "pycg_projection_lineage": [
                        {"projected_edge": ["main", "main.a"]}
                    ],
                },
            }
        ],
    }

    audit = audit_run(run)

    assert audit["evidence_status_counts"] == {
        "missing": 1,
        "projection_lineage_only": 1,
    }


def test_audit_attributes_inlined_synthetic_frame_to_parent() -> None:
    run = {
        "suite": "macro",
        "score": {},
        "cases": [
            {
                "suite_path": "sample",
                "status": "ok",
                "extra_edges": [["main.f", "<**PyStr**>.isupper"]],
                "analysis_evidence": {
                    "semantic_call_edge_evidence": [
                        _record(
                            ["main.f.<genexpr>", "<**PyStr**>.isupper"],
                            "any(ch.isupper() for ch in value)",
                        )
                    ],
                    "pycg_projection_lineage": [],
                },
            }
        ],
    }

    audit = audit_run(run)

    assert audit["evidence_status_counts"] == {
        "synthetic_frame_contextual_evidence": 1
    }


def test_audit_runs_aggregates_scores_and_categories() -> None:
    first = {
        "suite": "macro",
        "score": {
            "true_positive": 2,
            "recall_true_positive": 3,
            "false_positive": 1,
            "false_negative": 1,
        },
        "cases": [],
    }
    second = {
        "suite": "macro",
        "score": {
            "true_positive": 4,
            "recall_true_positive": 4,
            "false_positive": 1,
            "false_negative": 2,
        },
        "cases": [],
    }

    audit = audit_runs([first, second])

    assert audit["raw_score"] == {
        "true_positive": 6,
        "recall_true_positive": 7,
        "false_positive": 2,
        "false_negative": 3,
        "precision": 0.75,
        "recall": 0.7,
    }
