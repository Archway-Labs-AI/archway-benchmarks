from __future__ import annotations

import pytest

from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark
from archway_benchmarks.bugsinpy_agent_protocol import (
    AgentPair,
    AgentTrial,
    AgentUsage,
    EvidenceAdjudication,
    EvidenceQueryRecord,
)
from archway_benchmarks.bugsinpy_protocol import (
    ProtocolViolation,
    RankedFinding,
    RankedPredictionBundle,
)
from archway_benchmarks.bugsinpy_agent_scoring import score_agent_pairs


def _prediction(revision: str, findings=()) -> RankedPredictionBundle:
    return RankedPredictionBundle(
        protocol="repository-static-v1",
        bug_key="demoproj:1",
        buggy_revision=revision,
        findings=findings,
        repository_files=2,
        repository_loc=100,
        analyzed_files=2,
        analyzed_loc=100,
    )


def _trial(condition: str, invocation: str, prediction, *, query=False) -> AgentTrial:
    queries = (EvidenceQueryRecord(
        1, "binding-types", {"module": "demoproj.core", "binding": "total"},
        "answered", 0.2, "c" * 64,
    ),) if query else ()
    return AgentTrial(
        f"trial-{condition}", "pair-1", condition, invocation, "model-v1",
        {"max_output_tokens": 2000}, "b" * 64, prediction,
        "diagnosis", 3.0 if condition == "baseline" else 4.0,
        AgentUsage(100 if condition == "baseline" else 120, 20), queries,
    )


def test_paired_score_reports_localization_efficiency_and_disposition() -> None:
    benchmark = BugsInPyBenchmark(corpus_root="tests/fixtures/bugsinpy")
    bug = next(item for item in benchmark.load() if item.key == "demoproj:1")
    miss = _prediction(bug.buggy_commit)
    hit = _prediction(bug.buggy_commit, (
        RankedFinding(1, "demoproj/core.py", 11, 11, "agent-diagnosis"),
    ))
    pair = AgentPair(
        "pair-1", _trial("baseline", "inv-1", miss),
        _trial("archway-evidence", "inv-2", hit, query=True),
    )

    score = score_agent_pairs(
        benchmark, (pair,),
        adjudications=(EvidenceAdjudication("pair-1", 1, "useful", "localized value"),),
    )

    assert score["conditions"]["baseline"]["localization"]["top_line_hits"][1] == 0
    assert score["conditions"]["archway_evidence"]["localization"]["top_line_hits"][1] == 1
    assert score["paired_mean_delta"] == {
        "line_hit": 1.0,
        "reciprocal_rank": 1.0,
        "exam_score": -0.99,
        "tokens": 20.0,
        "duration_seconds": 1.0,
    }
    assert score["evidence_dispositions"]["useful"] == 1


def test_paired_score_requires_unique_pairs_and_complete_adjudication() -> None:
    benchmark = BugsInPyBenchmark(corpus_root="tests/fixtures/bugsinpy")
    bug = next(item for item in benchmark.load() if item.key == "demoproj:1")
    prediction = _prediction(bug.buggy_commit)
    pair = AgentPair(
        "pair-1", _trial("baseline", "inv-1", prediction),
        _trial("archway-evidence", "inv-2", prediction, query=True),
    )
    with pytest.raises(ProtocolViolation, match="adjudications"):
        score_agent_pairs(benchmark, (pair,), adjudications=())
    with pytest.raises(ProtocolViolation, match="unique"):
        score_agent_pairs(
            benchmark, (pair, pair),
            adjudications=(EvidenceAdjudication("pair-1", 1, "useful", "reason"),),
        )
