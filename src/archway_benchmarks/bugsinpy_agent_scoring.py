"""Paired localization and efficiency scoring for BugsInPy agent trials.

This module is top-level so BugsInPy-only use does not import the optional
TypeEvalPy scoring dependency through ``archway_benchmarks.scoring``.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from typing import TYPE_CHECKING, Iterable

from archway_benchmarks.bugsinpy_agent_protocol import (
    AgentPair,
    EvidenceAdjudication,
)
from archway_benchmarks.bugsinpy_protocol import ProtocolViolation
from archway_benchmarks.scoring.bugsinpy import score_ranked_detection

if TYPE_CHECKING:
    from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark


PAIRED_SCORE_SCHEMA = "archway.bugsinpy.agent-paired-score.v1"


def _mean(values: Iterable[float]) -> float:
    values = tuple(values)
    return sum(values) / len(values) if values else 0.0


def score_agent_pairs(
    benchmark: "BugsInPyBenchmark",
    pairs: Iterable[AgentPair],
    *,
    adjudications: Iterable[EvidenceAdjudication],
) -> dict[str, object]:
    """Join sealed arm predictions with ground truth and compare paired outcomes."""

    pairs = tuple(pairs)
    if not pairs:
        raise ProtocolViolation("paired agent score requires at least one pair")
    bug_keys = [pair.baseline.prediction.bug_key for pair in pairs]
    pair_ids = [pair.pair_id for pair in pairs]
    if len(set(bug_keys)) != len(bug_keys) or len(set(pair_ids)) != len(pair_ids):
        raise ProtocolViolation("paired agent score requires unique bug and pair identities")

    baseline_predictions = {
        pair.baseline.prediction.bug_key: pair.baseline.prediction for pair in pairs
    }
    evidence_predictions = {
        pair.archway_evidence.prediction.bug_key: pair.archway_evidence.prediction
        for pair in pairs
    }
    subset = set(bug_keys)
    baseline_scores, baseline_outcomes = score_ranked_detection(
        benchmark, baseline_predictions, subset=subset
    )
    evidence_scores, evidence_outcomes = score_ranked_detection(
        benchmark, evidence_predictions, subset=subset
    )
    baseline_by_key = {item.bug_key: item for item in baseline_outcomes}
    evidence_by_key = {item.bug_key: item for item in evidence_outcomes}

    expected_queries = {
        (pair.pair_id, query.sequence)
        for pair in pairs
        for query in pair.archway_evidence.queries
    }
    adjudications = tuple(adjudications)
    adjudication_keys = [(item.pair_id, item.query_sequence) for item in adjudications]
    if len(set(adjudication_keys)) != len(adjudication_keys):
        raise ProtocolViolation("evidence adjudications cannot repeat a query")
    if set(adjudication_keys) != expected_queries:
        raise ProtocolViolation("evidence adjudications must cover exactly the retained queries")
    dispositions = Counter(item.disposition for item in adjudications)

    rows = []
    for pair in pairs:
        key = pair.baseline.prediction.bug_key
        baseline = baseline_by_key[key]
        evidence = evidence_by_key[key]
        rows.append({
            "pair_id": pair.pair_id,
            "bug_key": key,
            "baseline": {
                "first_line_hit_rank": baseline.first_line_hit_rank,
                "reciprocal_rank": baseline.reciprocal_rank,
                "exam_score": baseline.exam_score,
                "tokens": pair.baseline.usage.total_tokens,
                "duration_seconds": pair.baseline.duration_seconds,
                "query_count": 0,
            },
            "archway_evidence": {
                "first_line_hit_rank": evidence.first_line_hit_rank,
                "reciprocal_rank": evidence.reciprocal_rank,
                "exam_score": evidence.exam_score,
                "tokens": pair.archway_evidence.usage.total_tokens,
                "duration_seconds": pair.archway_evidence.duration_seconds,
                "query_count": len(pair.archway_evidence.queries),
            },
            "delta": {
                "line_hit": int(evidence.first_line_hit_rank is not None)
                - int(baseline.first_line_hit_rank is not None),
                "reciprocal_rank": evidence.reciprocal_rank - baseline.reciprocal_rank,
                "exam_score": evidence.exam_score - baseline.exam_score,
                "tokens": pair.archway_evidence.usage.total_tokens
                - pair.baseline.usage.total_tokens,
                "duration_seconds": pair.archway_evidence.duration_seconds
                - pair.baseline.duration_seconds,
            },
        })

    return {
        "schema": PAIRED_SCORE_SCHEMA,
        "pair_count": len(pairs),
        "conditions": {
            "baseline": {
                "localization": dataclasses.asdict(baseline_scores),
                "mean_tokens": _mean(pair.baseline.usage.total_tokens for pair in pairs),
                "mean_duration_seconds": _mean(
                    pair.baseline.duration_seconds for pair in pairs
                ),
                "mean_query_count": 0.0,
            },
            "archway_evidence": {
                "localization": dataclasses.asdict(evidence_scores),
                "mean_tokens": _mean(
                    pair.archway_evidence.usage.total_tokens for pair in pairs
                ),
                "mean_duration_seconds": _mean(
                    pair.archway_evidence.duration_seconds for pair in pairs
                ),
                "mean_query_count": _mean(
                    len(pair.archway_evidence.queries) for pair in pairs
                ),
            },
        },
        "paired_mean_delta": {
            name: _mean(float(row["delta"][name]) for row in rows)
            for name in (
                "line_hit", "reciprocal_rank", "exam_score", "tokens",
                "duration_seconds",
            )
        },
        "evidence_dispositions": {
            name: dispositions[name]
            for name in ("useful", "irrelevant", "misleading", "unusable")
        },
        "pairs": rows,
    }
