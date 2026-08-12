"""Evidence-preserving triage for PyCG raw extra edges.

PyCG ground truth intentionally omits some calls that are semantically present
in a program.  This module does not reinterpret the score or declare those
edges correct.  It joins each raw extra to retained diagram-analysis evidence
and assigns a stable review category so semantic precision can be adjudicated
without rerunning one analysis per edge.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

Edge = tuple[str, str]


@dataclass(frozen=True)
class ExtraEdgeAudit:
    edge: Edge
    evidence_status: str
    semantic_category: str
    source_relationship: str
    callsite_count: int
    callsites: tuple[dict[str, Any], ...]
    target_competition: str
    callsite_candidate_edges: tuple[Edge, ...]
    expected_candidates_at_callsites: tuple[Edge, ...]

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "edge": list(self.edge),
            "evidence_status": self.evidence_status,
            "semantic_category": self.semantic_category,
            "source_relationship": self.source_relationship,
            "callsite_count": self.callsite_count,
            "callsites": list(self.callsites),
            "target_competition": self.target_competition,
            "callsite_candidate_edges": [list(edge) for edge in self.callsite_candidate_edges],
            "expected_candidates_at_callsites": [
                list(edge) for edge in self.expected_candidates_at_callsites
            ],
            # Classification is intentionally not adjudication.
            "disposition": "review_required",
        }


def _edge(value: Iterable[object]) -> Edge:
    caller, callee = value
    return str(caller), str(callee)


def _semantic_category(callee: str, records: list[Mapping[str, Any]]) -> str:
    target_kinds = {str(record.get("target_kind", "")) for record in records}
    if callee.endswith((".__enter__", ".__exit__", ".__iter__", ".__next__")):
        return "implicit_protocol_call"
    if callee.startswith(("<builtin>", "<builtin-method>", "<**")):
        return "builtin_or_runtime_call"
    if any("External" in kind for kind in target_kinds):
        return "external_dependency_call"
    return "project_or_resolved_object_call"


def _callee_lexemes(callee: str) -> tuple[str, ...]:
    leaf = callee.rsplit(".", 1)[-1]
    values = [leaf.strip("<>*")]
    if leaf.startswith("__") and leaf.endswith("__"):
        values.append(leaf.strip("_"))
    return tuple(value for value in values if value)


def _source_relationship(callee: str, records: list[Mapping[str, Any]]) -> str:
    lines = [str(record.get("source_line", "")) for record in records]
    lexemes = _callee_lexemes(callee)
    if any(re.search(rf"\b{re.escape(lexeme)}\b", line) for line in lines for lexeme in lexemes):
        return "callee_lexeme_visible"
    if callee.endswith((".__enter__", ".__exit__")) and any(
        re.search(r"\bwith\b", line) for line in lines
    ):
        return "syntax_implied_protocol"
    if records:
        return "diagram_resolved_indirectly"
    return "no_contextual_evidence"


def audit_case(case: Mapping[str, Any]) -> dict[str, Any]:
    evidence = case.get("analysis_evidence", {})
    contextual = evidence.get("semantic_call_edge_evidence", [])
    by_edge: dict[Edge, list[Mapping[str, Any]]] = defaultdict(list)
    by_callsite: dict[str, set[Edge]] = defaultdict(set)
    for record in contextual:
        projected = record.get("projected_edge")
        if isinstance(projected, list) and len(projected) == 2:
            projected_edge = _edge(projected)
            by_edge[projected_edge].append(record)
            callsite = record.get("callsite_morphism_id")
            if isinstance(callsite, str):
                by_callsite[callsite].add(projected_edge)

    # PyCG presents comprehensions as implementation-transparent frames.  The
    # scorer projection inlines those callers, while contextual semantic
    # evidence correctly retains the actual diagram boundary.  Preserve that
    # relationship explicitly instead of treating the projected edge as
    # evidence-free.
    synthetic_by_parent_edge: dict[Edge, list[Mapping[str, Any]]] = defaultdict(list)
    for (caller, callee), records in by_edge.items():
        marker = caller.find(".<")
        if marker >= 0:
            synthetic_by_parent_edge[(caller[:marker], callee)].extend(records)

    lineage_edges = {
        _edge(record["projected_edge"])
        for record in evidence.get("pycg_projection_lineage", [])
        if isinstance(record.get("projected_edge"), list)
        and len(record["projected_edge"]) == 2
    }

    audits: list[ExtraEdgeAudit] = []
    predicted = {_edge(value) for value in case.get("predicted_edges", [])}
    extras = {_edge(value) for value in case.get("extra_edges", [])}
    missing = {_edge(value) for value in case.get("missing_edges", [])}
    expected = (predicted - extras) | missing
    for edge in sorted(_edge(value) for value in case.get("extra_edges", [])):
        records = by_edge.get(edge, [])
        synthetic_records = synthetic_by_parent_edge.get(edge, [])
        if records:
            evidence_status = "contextual_semantic_evidence"
        elif synthetic_records:
            records = synthetic_records
            evidence_status = "synthetic_frame_contextual_evidence"
        elif edge in lineage_edges:
            evidence_status = "projection_lineage_only"
        else:
            evidence_status = "missing"
        callsites = tuple(
            {
                "callsite_morphism_id": record.get("callsite_morphism_id"),
                "source_module": record.get("source_module"),
                "source_position": record.get("source_position"),
                "source_line": record.get("source_line"),
                "target_kind": record.get("target_kind"),
                "invocation_kind": record.get("invocation_kind"),
            }
            for record in records
        )
        callsite_ids = {
            str(record.get("callsite_morphism_id"))
            for record in records
            if record.get("callsite_morphism_id")
        }
        candidates = tuple(
            sorted(
                candidate
                for callsite_id in callsite_ids
                for candidate in by_callsite.get(callsite_id, set())
            )
        )
        expected_candidates = tuple(candidate for candidate in candidates if candidate in expected)
        if expected_candidates:
            target_competition = "competes_with_expected_target"
        elif len(candidates) > 1:
            target_competition = "multiple_analyzer_targets"
        else:
            target_competition = "single_analyzer_target"
        audits.append(
            ExtraEdgeAudit(
                edge=edge,
                evidence_status=evidence_status,
                semantic_category=_semantic_category(edge[1], records),
                source_relationship=_source_relationship(edge[1], records),
                callsite_count=len({item.get("callsite_morphism_id") for item in records}),
                callsites=callsites,
                target_competition=target_competition,
                callsite_candidate_edges=candidates,
                expected_candidates_at_callsites=expected_candidates,
            )
        )

    evidence_counts = Counter(item.evidence_status for item in audits)
    category_counts = Counter(item.semantic_category for item in audits)
    relationship_counts = Counter(item.source_relationship for item in audits)
    competition_counts = Counter(item.target_competition for item in audits)
    return {
        "suite_path": case.get("suite_path"),
        "raw_extra_count": len(audits),
        "evidence_status_counts": dict(sorted(evidence_counts.items())),
        "semantic_category_counts": dict(sorted(category_counts.items())),
        "source_relationship_counts": dict(sorted(relationship_counts.items())),
        "target_competition_counts": dict(sorted(competition_counts.items())),
        "edges": [item.to_jsonable() for item in audits],
    }


def audit_run(run: Mapping[str, Any]) -> dict[str, Any]:
    cases = [audit_case(case) for case in run.get("cases", []) if case.get("status") == "ok"]
    evidence_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    relationship_counts: Counter[str] = Counter()
    competition_counts: Counter[str] = Counter()
    for case in cases:
        evidence_counts.update(case["evidence_status_counts"])
        category_counts.update(case["semantic_category_counts"])
        relationship_counts.update(case["source_relationship_counts"])
        competition_counts.update(case["target_competition_counts"])
    return {
        "schema": "archway.pycg.semantic-extra-audit.v1",
        "suite": run.get("suite"),
        "raw_score": run.get("score"),
        "raw_extra_count": sum(case["raw_extra_count"] for case in cases),
        "evidence_status_counts": dict(sorted(evidence_counts.items())),
        "semantic_category_counts": dict(sorted(category_counts.items())),
        "source_relationship_counts": dict(sorted(relationship_counts.items())),
        "target_competition_counts": dict(sorted(competition_counts.items())),
        "adjudication_policy": {
            "default_disposition": "review_required",
            "note": "Evidence categories do not change raw scores or assert semantic correctness.",
        },
        "cases": cases,
    }


def audit_runs(runs: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Audit several result artifacts as one revision-consistent evidence set."""

    audited = [audit_run(run) for run in runs]
    cases = [case for item in audited for case in item["cases"]]
    evidence_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    relationship_counts: Counter[str] = Counter()
    competition_counts: Counter[str] = Counter()
    score_counts: Counter[str] = Counter()
    for item in audited:
        evidence_counts.update(item["evidence_status_counts"])
        category_counts.update(item["semantic_category_counts"])
        relationship_counts.update(item["source_relationship_counts"])
        competition_counts.update(item["target_competition_counts"])
        item_score = item.get("raw_score") or {}
        score_counts.update(
            {
                key: int(item_score.get(key, 0))
                for key in {"true_positive", "false_positive", "false_negative"}
            }
        )
        score_counts["recall_true_positive"] += int(
            item_score.get("recall_true_positive", item_score.get("true_positive", 0))
        )
    precision_denominator = score_counts["true_positive"] + score_counts["false_positive"]
    recall_tp = score_counts["recall_true_positive"] or score_counts["true_positive"]
    recall_denominator = recall_tp + score_counts["false_negative"]
    raw_score = dict(score_counts)
    raw_score["precision"] = (
        score_counts["true_positive"] / precision_denominator if precision_denominator else 0.0
    )
    raw_score["recall"] = recall_tp / recall_denominator if recall_denominator else 0.0
    return {
        "schema": "archway.pycg.semantic-extra-audit.v1",
        "suite": "macro",
        "source_result_count": len(audited),
        "raw_score": raw_score,
        "raw_extra_count": sum(case["raw_extra_count"] for case in cases),
        "evidence_status_counts": dict(sorted(evidence_counts.items())),
        "semantic_category_counts": dict(sorted(category_counts.items())),
        "source_relationship_counts": dict(sorted(relationship_counts.items())),
        "target_competition_counts": dict(sorted(competition_counts.items())),
        "adjudication_policy": {
            "default_disposition": "review_required",
            "note": "Evidence categories do not change raw scores or assert semantic correctness.",
        },
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    runs = [json.loads(path.read_text(encoding="utf-8")) for path in args.result]
    audit = audit_run(runs[0]) if len(runs) == 1 else audit_runs(runs)
    payload = json.dumps(audit, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
