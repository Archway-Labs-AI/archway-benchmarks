"""Public scoring for proposal -> Archway evidence -> review interactions."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from .bugsinpy_agent_protocol import CausalEvidenceInteraction, ForkedEvidenceComparison
from .bugsinpy_protocol import ProtocolViolation
from .scoring.bugsinpy import score_ranked_detection

if TYPE_CHECKING:
    from .benchmarks.bugsinpy import BugsInPyBenchmark


CAUSAL_SCORE_SCHEMA = "archway.bugsinpy.agent-causal-score.v1"
FORKED_SCORE_SCHEMA = "archway.bugsinpy.agent-forked-score.v1"

_CAUSAL_KIND = "failing-test cause"
_ADDITIONAL_KIND = "additional unrelated bug"
_UNCERTAIN_KIND = "uncertain relation"


def _mean(values: Iterable[float]) -> float:
    values = tuple(values)
    return sum(values) / len(values) if values else 0.0


def _designated_prediction(prediction):
    """Score only findings explicitly claimed to explain test-directed failures."""
    if prediction.protocol != "test-directed-static-v1":
        return prediction
    findings = tuple(
        dataclasses.replace(finding, rank=rank)
        for rank, finding in enumerate(
            (item for item in prediction.findings if item.kind == _CAUSAL_KIND), 1
        )
    )
    return dataclasses.replace(prediction, findings=findings)


def _causal_roles(prediction) -> dict[str, int]:
    counts = Counter(item.kind for item in prediction.findings)
    return {
        "claimed_failure_causes": counts[_CAUSAL_KIND],
        "additional_unrelated_reported": counts[_ADDITIONAL_KIND],
        "uncertain_relation_reported": counts[_UNCERTAIN_KIND],
    }


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
        benchmark, {
            item.proposal.prediction.bug_key: _designated_prediction(item.proposal.prediction)
            for item in interactions
        },
        subset=subset,
    )
    review_scores, review_outcomes = score_ranked_detection(
        benchmark, {
            item.review.prediction.bug_key: _designated_prediction(item.review.prediction)
            for item in interactions
        },
        subset=subset,
    )
    if {item.bug_key for item in proposal_outcomes} != subset or {
        item.bug_key for item in review_outcomes
    } != subset:
        raise ProtocolViolation("causal score corpus does not contain every interaction bug")
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
            "causal_roles": {
                "proposal": _causal_roles(interaction.proposal.prediction),
                "review": _causal_roles(interaction.review.prediction),
            },
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


def score_forked_comparisons(
    benchmark: "BugsInPyBenchmark",
    comparisons: Iterable[ForkedEvidenceComparison],
) -> dict[str, object]:
    """Score evidence review against a matched second-pass control review."""
    comparisons = tuple(comparisons)
    if not comparisons:
        raise ProtocolViolation("forked score requires at least one comparison")
    keys = [item.proposal.prediction.bug_key for item in comparisons]
    ids = [item.comparison_id for item in comparisons]
    if len(set(keys)) != len(keys) or len(set(ids)) != len(ids):
        raise ProtocolViolation("forked score requires unique bug and comparison identities")
    subset = set(keys)

    def predictions(stage_name: str):
        return {
            item.proposal.prediction.bug_key: _designated_prediction(
                getattr(item, stage_name).prediction
            )
            for item in comparisons
        }

    proposal_scores, proposal_outcomes = score_ranked_detection(
        benchmark, predictions("proposal"), subset=subset,
    )
    control_scores, control_outcomes = score_ranked_detection(
        benchmark, predictions("control_review"), subset=subset,
    )
    evidence_scores, evidence_outcomes = score_ranked_detection(
        benchmark, predictions("evidence_review"), subset=subset,
    )
    for outcomes in (proposal_outcomes, control_outcomes, evidence_outcomes):
        if {item.bug_key for item in outcomes} != subset:
            raise ProtocolViolation("forked score corpus does not contain every comparison bug")
    proposal_by_key = {item.bug_key: item for item in proposal_outcomes}
    control_by_key = {item.bug_key: item for item in control_outcomes}
    evidence_by_key = {item.bug_key: item for item in evidence_outcomes}
    rows = []
    for comparison in comparisons:
        key = comparison.proposal.prediction.bug_key
        proposal = proposal_by_key[key]
        control = control_by_key[key]
        evidence = evidence_by_key[key]

        def delta(left, right):
            return {
                "line_hit": int(right.first_line_hit_rank is not None)
                - int(left.first_line_hit_rank is not None),
                "reciprocal_rank": right.reciprocal_rank - left.reciprocal_rank,
                "exam_score": right.exam_score - left.exam_score,
            }

        rows.append({
            "comparison_id": comparison.comparison_id,
            "bug_key": key,
            "proposal": dataclasses.asdict(proposal),
            "control_review": dataclasses.asdict(control),
            "evidence_review": dataclasses.asdict(evidence),
            "causal_roles": {
                "proposal": _causal_roles(comparison.proposal.prediction),
                "control_review": _causal_roles(comparison.control_review.prediction),
                "evidence_review": _causal_roles(comparison.evidence_review.prediction),
            },
            "primary_delta_evidence_vs_control": delta(control, evidence),
            "secondary_delta_control_vs_proposal": delta(proposal, control),
            "secondary_delta_evidence_vs_proposal": delta(proposal, evidence),
            "evidence": {
                "kind": comparison.evidence_query.kind,
                "response_status": comparison.evidence_query.response_status,
                "duration_seconds": comparison.evidence_query.duration_seconds,
                "disposition": comparison.evidence_disposition,
                "review_order": list(comparison.review_order),
            },
        })
    dispositions = Counter(item.evidence_disposition for item in comparisons)
    primary_names = ("line_hit", "reciprocal_rank", "exam_score")
    return {
        "schema": FORKED_SCORE_SCHEMA,
        "comparison_count": len(comparisons),
        "primary_estimand": "evidence_review_minus_matched_control_review",
        "conditions": {
            "proposal": {"localization": dataclasses.asdict(proposal_scores)},
            "control_review": {"localization": dataclasses.asdict(control_scores)},
            "evidence_review": {"localization": dataclasses.asdict(evidence_scores)},
        },
        "primary_mean_delta": {
            name: _mean(
                float(row["primary_delta_evidence_vs_control"][name]) for row in rows
            )
            for name in primary_names
        },
        "efficiency": {
            "mean_shared_proposal_tokens": _mean(
                item.proposal.usage.total_tokens for item in comparisons
            ),
            "mean_control_review_tokens": _mean(
                item.control_review.usage.total_tokens for item in comparisons
            ),
            "mean_evidence_review_tokens": _mean(
                item.evidence_review.usage.total_tokens for item in comparisons
            ),
            "mean_evidence_minus_control_review_tokens": _mean(
                item.evidence_review.usage.total_tokens
                - item.control_review.usage.total_tokens
                for item in comparisons
            ),
            "mean_control_total_seconds": _mean(
                item.proposal.duration_seconds + item.control_review.duration_seconds
                for item in comparisons
            ),
            "mean_evidence_total_seconds": _mean(
                item.proposal.duration_seconds + item.evidence_query.duration_seconds
                + item.evidence_review.duration_seconds
                for item in comparisons
            ),
            "control_query_count": 0.0,
            "evidence_query_count": 1.0,
        },
        "evidence_dispositions": {
            label: dispositions[label]
            for label in ("useful", "irrelevant", "misleading", "unusable")
        },
        "comparisons": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--interaction", type=Path, action="append")
    sources.add_argument("--comparison", type=Path, action="append")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output must not already exist")
    from .benchmarks.bugsinpy import BugsInPyBenchmark
    try:
        benchmark = BugsInPyBenchmark(args.corpus_root)
        if args.comparison:
            comparisons = tuple(
                ForkedEvidenceComparison.from_json(
                    json.loads(path.read_text(encoding="utf-8"))
                )
                for path in args.comparison
            )
            score = score_forked_comparisons(benchmark, comparisons)
        else:
            interactions = tuple(
                CausalEvidenceInteraction.from_json(
                    json.loads(path.read_text(encoding="utf-8"))
                )
                for path in args.interaction
            )
            score = score_causal_interactions(benchmark, interactions)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(f".{args.output.name}.partial")
        temporary.write_text(
            json.dumps(score, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
