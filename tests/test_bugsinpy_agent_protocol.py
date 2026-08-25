from __future__ import annotations

import pytest

from archway_benchmarks.bugsinpy_agent_protocol import (
    AgentPair,
    AgentTrial,
    AgentUsage,
    CausalEvidenceInteraction,
    CausalStage,
    EvidenceQueryRecord,
    ForkedEvidenceComparison,
)
from archway_benchmarks.bugsinpy_protocol import (
    ProtocolViolation,
    RankedFinding,
    RankedPredictionBundle,
)


def prediction() -> RankedPredictionBundle:
    return RankedPredictionBundle(
        protocol="repository-static-v1",
        bug_key="PySnooper:3",
        buggy_revision="a" * 40,
        findings=(RankedFinding(1, "pysnooper.py", 26, 26, "agent-diagnosis"),),
        repository_files=9,
        repository_loc=684,
        analyzed_files=9,
        analyzed_loc=684,
    )


def trial(condition: str, invocation: str, *, queries=()) -> AgentTrial:
    return AgentTrial(
        trial_id=f"trial-{condition}",
        pair_id="pair-1",
        condition=condition,
        invocation_id=invocation,
        model_id="model-v1",
        model_config={"max_output_tokens": 2000, "temperature": 0},
        detector_input_sha256="b" * 64,
        prediction=prediction(),
        diagnosis="output_path is undefined",
        duration_seconds=2.5,
        usage=AgentUsage(100, 20),
        queries=queries,
    )


def query() -> EvidenceQueryRecord:
    return EvidenceQueryRecord(
        sequence=1,
        kind="possible-calls",
        request={"module": "pysnooper.pysnooper", "row": 26, "col": 17},
        response_status="answered",
        duration_seconds=0.4,
        response_sha256="c" * 64,
    )


def test_valid_pair_requires_independent_equal_arms() -> None:
    pair = AgentPair("pair-1", trial("baseline", "inv-1"), trial(
        "archway-evidence", "inv-2", queries=(query(),)
    ))
    assert pair.to_json()["archway_evidence"]["queries"][0]["kind"] == "possible-calls"
    assert AgentPair.from_json(pair.to_json()) == pair


def test_baseline_cannot_claim_archway_queries() -> None:
    with pytest.raises(ProtocolViolation, match="baseline"):
        trial("baseline", "inv-1", queries=(query(),))


def test_pair_rejects_shared_context_or_different_budget() -> None:
    with pytest.raises(ProtocolViolation, match="independent"):
        AgentPair("pair-1", trial("baseline", "same"), trial("archway-evidence", "same"))
    changed = trial("archway-evidence", "inv-2")
    object.__setattr__(changed, "model_config", {"max_output_tokens": 4000})
    with pytest.raises(ProtocolViolation, match="model_config"):
        AgentPair("pair-1", trial("baseline", "inv-1"), changed)


def test_trial_rejects_ground_truth_shaped_query_and_missing_usage() -> None:
    with pytest.raises(ProtocolViolation, match="forbidden"):
        EvidenceQueryRecord(
            1, "possible-calls", {"files_touched": ["answer.py"]},
            "answered", 0.1, "d" * 64,
        )
    with pytest.raises(TypeError):
        AgentTrial(  # type: ignore[call-arg]
            "trial", "pair-1", "baseline", "inv", "model", {}, "b" * 64,
            prediction(), "diagnosis", 1.0,
        )


def test_pair_json_rejects_unknown_fields() -> None:
    pair = AgentPair(
        "pair-1", trial("baseline", "inv-1"),
        trial("archway-evidence", "inv-2", queries=(query(),)),
    ).to_json()
    pair["ground_truth"] = {"file": "answer.py"}
    with pytest.raises(ProtocolViolation, match="fields"):
        AgentPair.from_json(pair)


def test_causal_interaction_roundtrip_requires_independent_stages() -> None:
    interaction = CausalEvidenceInteraction(
        "interaction-1", "model-v1", {"max_output_tokens": 2000}, "b" * 64,
        CausalStage("inv-proposal", prediction(), "before", 2.0, AgentUsage(100, 20)),
        CausalStage("inv-review", prediction(), "after", 1.0, AgentUsage(50, 10)),
        query(), "output path may be wrong", "output_path is undefined",
        "confirmed", True, "useful", "The argument evidence identifies output_path.",
    )
    assert CausalEvidenceInteraction.from_json(interaction.to_json()) == interaction
    with pytest.raises(ProtocolViolation, match="independent"):
        CausalEvidenceInteraction(
            "interaction-1", "model-v1", {}, "b" * 64,
            CausalStage("same", prediction(), "before", 1.0, AgentUsage(1, 1)),
            CausalStage("same", prediction(), "after", 1.0, AgentUsage(1, 1)),
            query(), "before", "after", "confirmed", True, "useful", "reason",
        )


def test_forked_comparison_requires_matched_query_and_true_control() -> None:
    stage = lambda invocation: CausalStage(
        invocation, prediction(), invocation, 1.0, AgentUsage(1, 1)
    )
    request = query().request
    control = EvidenceQueryRecord(
        1, "possible-calls", request, "not_collected", 0.0, "d" * 64
    )
    evidence = EvidenceQueryRecord(
        1, "possible-calls", request, "answered", 0.4, "c" * 64
    )
    comparison = ForkedEvidenceComparison(
        "comparison-1", "model", {}, "b" * 64,
        stage("proposal"), stage("control"), stage("evidence"), control, evidence,
        "before", "control after", "evidence after", "reranked", "confirmed",
        True, True, ("evidence", "control"), "useful", "reason",
    )
    assert ForkedEvidenceComparison.from_json(comparison.to_json()) == comparison

    mismatched = EvidenceQueryRecord(
        1, "possible-calls", {**request, "row": 27}, "answered", 0.4, "c" * 64
    )
    with pytest.raises(ProtocolViolation, match="same query"):
        ForkedEvidenceComparison(
            "comparison-1", "model", {}, "b" * 64,
            stage("proposal"), stage("control"), stage("evidence"),
            control, mismatched, "before", "control after", "evidence after",
            "reranked", "confirmed", True, True, ("control", "evidence"),
            "useful", "reason",
        )

    executed_control = EvidenceQueryRecord(
        1, "possible-calls", request, "not_collected", 0.1, "d" * 64
    )
    with pytest.raises(ProtocolViolation, match="deliberately not collected"):
        ForkedEvidenceComparison(
            "comparison-1", "model", {}, "b" * 64,
            stage("proposal"), stage("control"), stage("evidence"),
            executed_control, evidence, "before", "control after", "evidence after",
            "reranked", "confirmed", True, True, ("control", "evidence"),
            "useful", "reason",
        )
