"""Build an evidence-preserving, adjudicable PyCG residual inventory.

The raw benchmark score is immutable input. Automated evidence linkage and
clustering are diagnostic suggestions, never semantic adjudications. Reviewed
dispositions live in a separate manifest keyed by stable residual identity so
analysis, benchmark adaptation, scoring, and human review remain distinct.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .pycg_semantic_audit import audit_case as audit_extra_case


Edge = tuple[str, str]

_DISPOSITIONS = frozenset({
    "pending",
    "semantically_valid_extra",
    "benchmark_defect_or_omission",
    "adapter_representation_mismatch",
    "archway_precision_gap",
    "archway_unsoundness",
    "translation_or_ir_defect",
    "unsupported_semantics",
    "inconclusive",
})


def _edge(value: Iterable[object]) -> Edge:
    caller, callee = value
    return str(caller), str(callee)


def residual_id(suite_path: str, kind: str, edge: Edge) -> str:
    payload = json.dumps(
        [suite_path, kind, *edge], separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "pycg-residual:v1:" + hashlib.sha256(payload).hexdigest()


def _callee_lexemes(callee: str) -> tuple[str, ...]:
    leaf = callee.rsplit(".", 1)[-1]
    values = {leaf.strip("<>*"), leaf.strip("_<>*")}
    return tuple(sorted(value for value in values if value))


def _source_mentions_callee(record: Mapping[str, Any], callee: str) -> bool:
    line = str(record.get("source_line", ""))
    return any(
        re.search(rf"\b{re.escape(lexeme)}\b", line)
        for lexeme in _callee_lexemes(callee)
    )


def _evidence_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "projected_edge": record.get("projected_edge"),
        "semantic_edge": record.get("semantic_edge"),
        "callsite_morphism_id": record.get("callsite_morphism_id"),
        "source_module": record.get("source_module"),
        "source_position": record.get("source_position"),
        "source_line": record.get("source_line"),
        "target_kind": record.get("target_kind"),
        "evidence_grade": record.get("evidence_grade", "semantic"),
        "invocation_kind": record.get("invocation_kind"),
    }


def _review(
    residual: str, adjudications: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    supplied = adjudications.get(residual)
    if supplied is None:
        return {
            "status": "pending",
            "disposition": "pending",
            "reviewer": None,
            "rationale": None,
            "evidence_refs": [],
        }
    disposition = str(supplied.get("disposition", ""))
    if disposition not in _DISPOSITIONS - {"pending"}:
        raise ValueError(
            f"invalid adjudication disposition for {residual}: {disposition!r}"
        )
    reviewer = supplied.get("reviewer")
    rationale = supplied.get("rationale")
    evidence_refs = supplied.get("evidence_refs")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError(f"reviewed residual lacks reviewer: {residual}")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError(f"reviewed residual lacks rationale: {residual}")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise ValueError(f"reviewed residual lacks evidence refs: {residual}")
    return {
        "status": "reviewed",
        "disposition": disposition,
        "reviewer": reviewer,
        "rationale": rationale,
        "evidence_refs": evidence_refs,
    }


def _adjudications(manifest: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if manifest is None:
        return {}
    if manifest.get("schema") != "archway.pycg.residual-adjudications.v1":
        raise ValueError("unsupported PyCG residual adjudication schema")
    entries = manifest.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("adjudication entries must be a list")
    indexed: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("adjudication entry must be an object")
        identity = entry.get("residual_id")
        if not isinstance(identity, str) or not identity:
            raise ValueError("adjudication entry lacks residual_id")
        if identity in indexed:
            raise ValueError(f"duplicate residual adjudication: {identity}")
        indexed[identity] = entry
    return indexed


def audit_case(
    case: Mapping[str, Any],
    *,
    adjudications: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    suite_path = str(case.get("suite_path", ""))
    reviews = adjudications or {}
    evidence = case.get("analysis_evidence", {})
    contextual = evidence.get("semantic_call_edge_evidence", [])
    by_caller: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in contextual:
        projected = record.get("projected_edge")
        if isinstance(projected, list) and len(projected) == 2:
            by_caller[str(projected[0])].append(record)

    extras = {
        _edge(item["edge"]): item
        for item in audit_extra_case(case)["edges"]
    }
    residuals: list[dict[str, Any]] = []
    for edge in sorted(_edge(value) for value in case.get("extra_edges", [])):
        identity = residual_id(suite_path, "false_positive", edge)
        extra = extras[edge]
        residuals.append({
            "residual_id": identity,
            "kind": "false_positive",
            "edge": list(edge),
            "automated_cluster": extra["semantic_category"],
            "automated_evidence_status": extra["evidence_status"],
            "automated_target_competition": extra["target_competition"],
            "callsite_evidence": extra["callsites"],
            "candidate_edges": extra["callsite_candidate_edges"],
            "review": _review(identity, reviews),
        })

    lineage = evidence.get("pycg_projection_lineage", [])
    for edge in sorted(_edge(value) for value in case.get("missing_edges", [])):
        identity = residual_id(suite_path, "false_negative", edge)
        caller_records = by_caller.get(edge[0], [])
        lexical = [
            record for record in caller_records
            if _source_mentions_callee(record, edge[1])
        ]
        lineage_mentions = [
            record for record in lineage
            if edge in {
                _edge(value)
                for key in ("input_edge", "output_edge", "projected_edge")
                if isinstance((value := record.get(key)), list)
                and len(value) == 2
            }
        ]
        candidate_edges = sorted({
            _edge(record["projected_edge"])
            for record in caller_records
            if isinstance(record.get("projected_edge"), list)
            and len(record["projected_edge"]) == 2
        })
        if lineage_mentions:
            cluster = "projection_or_adapter_candidate"
            status = "projection_lineage_mentions_expected_edge"
        elif lexical:
            cluster = "wrong_or_missing_target_at_observed_callsite"
            status = "same_caller_lexical_callsite_candidate"
        elif caller_records:
            cluster = "missing_callsite_or_target"
            status = "same_caller_semantic_evidence_only"
        else:
            cluster = "missing_caller_analysis"
            status = "no_same_caller_semantic_evidence"
        residuals.append({
            "residual_id": identity,
            "kind": "false_negative",
            "edge": list(edge),
            "automated_cluster": cluster,
            "automated_evidence_status": status,
            "same_caller_edge_count": len(candidate_edges),
            "candidate_edges": [list(value) for value in candidate_edges],
            "lexical_callsite_evidence": [
                _evidence_projection(record) for record in lexical
            ],
            "projection_lineage_mentions": lineage_mentions,
            "review": _review(identity, reviews),
        })

    kind_counts = Counter(item["kind"] for item in residuals)
    cluster_counts = Counter(item["automated_cluster"] for item in residuals)
    review_counts = Counter(item["review"]["disposition"] for item in residuals)
    case_score = case.get("score") or {}
    scored_occurrences = (
        int(case_score.get("false_positive", kind_counts["false_positive"]))
        + int(case_score.get("false_negative", kind_counts["false_negative"]))
    )
    return {
        "suite_path": suite_path,
        "unique_residual_count": len(residuals),
        "scored_residual_occurrence_count": scored_occurrences,
        "duplicate_expected_occurrence_count": (
            int(case_score.get("false_negative", kind_counts["false_negative"]))
            - kind_counts["false_negative"]
        ),
        "kind_counts": dict(sorted(kind_counts.items())),
        "automated_cluster_counts": dict(sorted(cluster_counts.items())),
        "review_disposition_counts": dict(sorted(review_counts.items())),
        "residuals": residuals,
    }


def audit_run(
    run: Mapping[str, Any],
    *,
    adjudication_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    reviews = _adjudications(adjudication_manifest)
    cases = [
        audit_case(case, adjudications=reviews)
        for case in run.get("cases", [])
        if case.get("status") == "ok"
    ]
    present = {
        item["residual_id"]
        for case in cases
        for item in case["residuals"]
    }
    stale = sorted(set(reviews) - present)
    if stale:
        raise ValueError(f"adjudications reference absent residuals: {stale!r}")
    kind_counts: Counter[str] = Counter()
    cluster_counts: Counter[str] = Counter()
    review_counts: Counter[str] = Counter()
    for case in cases:
        kind_counts.update(case["kind_counts"])
        cluster_counts.update(case["automated_cluster_counts"])
        review_counts.update(case["review_disposition_counts"])
    return {
        "schema": "archway.pycg.residual-audit.v1",
        "suite": run.get("suite"),
        "raw_score": run.get("score"),
        "analysis_adapter_scorer_boundary": {
            "analysis": "produces diagram-derived semantic call edges",
            "adapter": "normalizes identities and records projection lineage",
            "scorer": "compares adapted edges with immutable benchmark expectations",
            "automated_clusters_are_adjudications": False,
        },
        "unique_residual_count": sum(
            case["unique_residual_count"] for case in cases
        ),
        "scored_residual_occurrence_count": sum(
            case["scored_residual_occurrence_count"] for case in cases
        ),
        "duplicate_expected_occurrence_count": sum(
            case["duplicate_expected_occurrence_count"] for case in cases
        ),
        "kind_counts": dict(sorted(kind_counts.items())),
        "automated_cluster_counts": dict(sorted(cluster_counts.items())),
        "review_disposition_counts": dict(sorted(review_counts.items())),
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--adjudications", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    run = json.loads(args.result.read_text(encoding="utf-8"))
    manifest = None
    if args.adjudications is not None:
        entries: list[object] = []
        for path in args.adjudications:
            item = json.loads(path.read_text(encoding="utf-8"))
            if item.get("schema") != "archway.pycg.residual-adjudications.v1":
                raise ValueError(f"unsupported adjudication schema: {path}")
            entries.extend(item.get("entries", []))
        manifest = {
            "schema": "archway.pycg.residual-adjudications.v1",
            "entries": entries,
        }
    audit = audit_run(run, adjudication_manifest=manifest)
    payload = json.dumps(audit, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
