"""Public scoring for proposal -> Archway evidence -> review interactions."""

from __future__ import annotations

import dataclasses
from collections import Counter
from typing import TYPE_CHECKING, Iterable

from .bugsinpy_agent_protocol import CausalEvidenceInteraction
from .bugsinpy_protocol import ProtocolViolation
from .scoring.bugsinpy import score_ranked_detection

if TYPE_CHECKING:
    from .benchmarks.bugsinpy import BugsInPyBenchmark


CAUSAL_SCORE_SCHEMA = "archway.bugsinpy.agent-causal-score.v1"


def _mean(values: Iterable[float]) -> float:
    values = tuple(values)
    return sum(values) / len(values) if values else 0.0


def score_causal_interactions(
    benchmark: "BugsInPyBenchmark",
    interactions: Iterable[CausalEvidenceInteraction],
) -> dict[str, object]:
    interactions = tuple(interactions)
    if not interactions:
        raise ProtocolViolation("causal score requires at least one interaction")
    keys = [item.proposal.prediction.bug_key for item in interactions]
    ids = [item.interaction_id for item in interactions]
    if len(set(keys)) != len(keys) or len(set(ids)) != len(ids):
        raise ProtocolViolation("causal score requires unique bug and interaction identities")
    subset = set(keys)
    proposal_scores, proposal_outcomes = score_ranked_detection(
        benchmark, {item.proposal.prediction.bug_key: item.proposal.prediction for item in interactions},
        subset=subset,
    )
    review_scores, review_outcomes = score_ranked_detection(
        benchmark, {item.review.prediction.bug_key: item.review.prediction for item in interactions},
        subset=subset,
    )
    before = {item.bug_key: item for item in proposal_outcomes}
    after = {item.bug_key: item for item in review_outcomes}
    rows = []
    for interaction in interactions:
        key = interaction.proposal.prediction.bug_key
        left, right = before[key], after[key]
        rows.append({
            "interaction_id": interaction.interaction_id,
            "bug_key": key,
            "proposal": dataclasses.asdict(left),
            "review": dataclasses.asdict(right),
            "delta": {
                "line_hit": int(right.first_line_hit_rank is not None)
                - int(left.first_line_hit_rank is not None),
                "reciprocal_rank": right.reciprocal_rank - left.reciprocal_rank,
                "exam_score": right.exam_score - left.exam_score,
            },
            "evidence": {
                "kind": interaction.query.kind,
                "response_status": interaction.query.response_status,
                "duration_seconds": interaction.query.duration_seconds,
                "disposition": interaction.evidence_disposition,
                "impact": interaction.evidence_impact,
            },
        })
    dispositions = Counter(item.evidence_disposition for item in interactions)
    return {
        "schema": CAUSAL_SCORE_SCHEMA,
        "interaction_count": len(interactions),
        "conditions": {
            "proposal": {"localization": dataclasses.asdict(proposal_scores)},
            "review": {"localization": dataclasses.asdict(review_scores)},
        },
        "mean_delta": {
            name: _mean(float(row["delta"][name]) for row in rows)
            for name in ("line_hit", "reciprocal_rank", "exam_score")
        },
        "efficiency": {
            "mean_proposal_tokens": _mean(
                item.proposal.usage.total_tokens for item in interactions
            ),
            "mean_review_increment_tokens": _mean(
                item.review.usage.total_tokens for item in interactions
            ),
            "mean_total_tokens": _mean(
                item.proposal.usage.total_tokens + item.review.usage.total_tokens
                for item in interactions
            ),
            "mean_query_count": 1.0,
            "mean_query_seconds": _mean(
                item.query.duration_seconds for item in interactions
            ),
            "mean_total_seconds": _mean(
                item.proposal.duration_seconds + item.query.duration_seconds
                + item.review.duration_seconds for item in interactions
            ),
        },
        "evidence_dispositions": {
            label: dispositions[label]
            for label in ("useful", "irrelevant", "misleading", "unusable")
        },
        "interactions": rows,
    }
