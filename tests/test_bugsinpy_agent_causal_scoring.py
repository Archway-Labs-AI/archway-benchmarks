from __future__ import annotations

from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark
from archway_benchmarks.bugsinpy_agent_causal_scoring import score_causal_interactions
from archway_benchmarks.bugsinpy_agent_protocol import (
    AgentUsage, CausalEvidenceInteraction, CausalStage, EvidenceQueryRecord,
)
from archway_benchmarks.bugsinpy_protocol import RankedFinding, RankedPredictionBundle


def _prediction(revision: str, hit: bool) -> RankedPredictionBundle:
    findings = (
        (RankedFinding(1, "demoproj/core.py", 11, 11, "agent-diagnosis"),)
        if hit else ()
    )
    return RankedPredictionBundle(
        "repository-static-v1", "demoproj:1", revision, findings, 2, 100, 2, 100,
    )


def test_causal_score_reports_accuracy_cost_and_evidence_quality() -> None:
    benchmark = BugsInPyBenchmark(corpus_root="tests/fixtures/bugsinpy")
    bug = next(item for item in benchmark.load() if item.key == "demoproj:1")
    interaction = CausalEvidenceInteraction(
        "interaction-1", "model-v1", {}, "b" * 64,
        CausalStage(
            "inv-proposal", _prediction(bug.buggy_commit, False), "before", 3.0,
            AgentUsage(100, 20),
        ),
        CausalStage(
            "inv-review", _prediction(bug.buggy_commit, True), "after", 2.0,
            AgentUsage(50, 10),
        ),
        EvidenceQueryRecord(
            1, "call-arguments", {"module": "demoproj.core", "row": 11, "col": 4},
            "answered", 0.5, "c" * 64,
        ),
        "argument may be wrong", "argument is wrong", "confirmed", True,
        "useful", "The mapping localized the patched argument.",
    )

    score = score_causal_interactions(benchmark, (interaction,))

    assert score["conditions"]["proposal"]["localization"]["top_line_hits"][1] == 0
    assert score["conditions"]["review"]["localization"]["top_line_hits"][1] == 1
    assert score["mean_delta"] == {
        "line_hit": 1.0, "reciprocal_rank": 1.0, "exam_score": -0.99,
    }
    assert score["efficiency"] == {
        "mean_proposal_tokens": 120.0,
        "mean_review_increment_tokens": 60.0,
        "mean_total_tokens": 180.0,
        "mean_query_count": 1.0,
        "mean_query_seconds": 0.5,
        "mean_total_seconds": 5.5,
    }
    assert score["evidence_dispositions"] == {
        "useful": 1, "irrelevant": 0, "misleading": 0, "unusable": 0,
    }
