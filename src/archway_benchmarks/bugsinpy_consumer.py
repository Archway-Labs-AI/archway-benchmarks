"""Bottom-only BugsInPy ``FindingCandidate`` consumer.

This module reads the existing BugsInPy flagger/driver artifact shape:

    manifest: [{"key": "...", "files": [{"repo_path": "..."}]}]
    results:  {bug_key: {repo_path: {"status": "analyzed", "bottom_rows": [...]}}}

It emits two separated outputs:

* strict flags in the scorer shape, containing only row-positioned bottom facts
  from strict-eligible source-position bases.
* diagnostic ``FindingCandidate`` records for every bottom fact, including
  rejected rowless, fallback, and undeclared-file facts.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from archway_benchmarks.bugsinpy_types import FindingCandidate, SourcePositionBasis

STRICT_POSITION_BASES = {"direct-node", "defining-expr"}


@dataclass(frozen=True)
class ConsumerOutput:
    flags_strict: dict[str, list[dict[str, Any]]]
    candidates_diagnostic: dict[str, Any]
    status_report: dict[str, Any]


def consume_bottom_findings(manifest: list[dict[str, Any]], results: dict[str, Any]) -> ConsumerOutput:
    """Convert existing bottom rows into strict flags plus diagnostics."""

    candidates: list[FindingCandidate] = []
    flags_by_bug_file: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    per_bug: dict[str, Any] = {}
    status_counter: Counter = Counter()
    classification_counter: Counter = Counter()
    bugs_analyzed_any = 0
    bugs_strict_flagged_any = 0

    for bug in manifest:
        bug_key = bug["key"]
        declared_files = {f["repo_path"] for f in bug.get("files", [])}
        bug_results = results.get(bug_key, {})
        files_to_visit = list(declared_files)
        for result_file in bug_results:
            if result_file not in declared_files:
                files_to_visit.append(result_file)

        file_status: dict[str, Any] = {}
        analyzed_any = False
        strict_flagged_any = False
        for repo_path in files_to_visit:
            r = bug_results.get(repo_path, {})
            st = r.get("status", "missing")
            status_counter[st] += 1
            if st == "analyzed":
                analyzed_any = True

            file_candidates = _candidates_for_file(
                bug_key=bug_key,
                repo_path=repo_path,
                result=r,
                file_declared=repo_path in declared_files,
            )
            for cand in file_candidates:
                candidates.append(cand)
                classification_counter[cand.provenance_classification] += 1
                if cand.strict_score_eligible and cand.file and cand.line is not None:
                    flags_by_bug_file[bug_key][cand.file].add(cand.line)
                    strict_flagged_any = True

            file_status[repo_path] = {
                "status": st,
                "n_bindings": r.get("n_bindings", 0),
                "n_bottom": r.get("n_bottom", 0),
                "bottom_rows": r.get("bottom_rows") or [],
                "error": r.get("error"),
                "candidate_count": len(file_candidates),
                "strict_candidate_count": sum(c.strict_score_eligible for c in file_candidates),
            }

        if analyzed_any:
            bugs_analyzed_any += 1
        if strict_flagged_any:
            bugs_strict_flagged_any += 1
        per_bug[bug_key] = {
            "project": bug.get("project"),
            "files": file_status,
            "analyzed_any": analyzed_any,
            "strict_flagged_any": strict_flagged_any,
        }

    flags_strict = {
        bug_key: [
            {"file": repo_path, "lines": sorted(lines)}
            for repo_path, lines in sorted(file_map.items())
            if lines
        ]
        for bug_key, file_map in sorted(flags_by_bug_file.items())
        if file_map
    }
    diagnostic = {
        "schema": "archway.bugsinpy.finding_candidates.v1",
        "signal_scope": "bottom-only",
        "strict_position_bases": sorted(STRICT_POSITION_BASES),
        "summary": {
            "total_candidates": len(candidates),
            "strict_eligible_candidates": sum(c.strict_score_eligible for c in candidates),
            "classification_counts": dict(sorted(classification_counter.items())),
        },
        "candidates": [c.to_json() for c in candidates],
    }
    status_report = {
        "total_bugs": len(manifest),
        "bugs_analyzed_any": bugs_analyzed_any,
        "bugs_strict_flagged_any": bugs_strict_flagged_any,
        "file_status_counts": dict(status_counter),
        "candidate_classification_counts": dict(sorted(classification_counter.items())),
        "per_bug": per_bug,
    }
    return ConsumerOutput(flags_strict, diagnostic, status_report)


def _candidates_for_file(
    *,
    bug_key: str,
    repo_path: str,
    result: dict[str, Any],
    file_declared: bool,
) -> list[FindingCandidate]:
    rows = result.get("bottom_rows") or []
    candidates = [
        _candidate_from_row(
            bug_key=bug_key,
            repo_path=repo_path,
            raw=row,
            file_declared=file_declared,
            row_index=index,
            result=result,
        )
        for index, row in enumerate(rows)
    ]

    n_bottom = result.get("n_bottom")
    if isinstance(n_bottom, int) and n_bottom > len(rows):
        for index in range(len(rows), n_bottom):
            candidates.append(
                _candidate_from_row(
                    bug_key=bug_key,
                    repo_path=repo_path if file_declared else None,
                    raw=None,
                    file_declared=file_declared,
                    row_index=index,
                    result=result,
                )
            )
    return candidates


def _candidate_from_row(
    *,
    bug_key: str,
    repo_path: str | None,
    raw: Any,
    file_declared: bool,
    row_index: int,
    result: dict[str, Any],
) -> FindingCandidate:
    line, span, basis, facts, raw_provenance = _parse_bottom_row(raw)
    if not file_declared and repo_path is not None:
        classification = "wrong-file"
        strict = False
    elif line is None:
        classification = "rowless"
        strict = False
        basis = "rowless"
    elif basis in STRICT_POSITION_BASES:
        classification = "strict-eligible"
        strict = True
    elif basis == "enclosing-function":
        classification = "enclosing-function-fallback"
        strict = False
    else:
        classification = "diagnostic-only"
        strict = False

    provenance = {
        "result_status": result.get("status"),
        "row_index": row_index,
        "facts_used": facts or ["bottom"],
    }
    if raw_provenance:
        provenance.update(raw_provenance)

    return FindingCandidate(
        bug_key=bug_key,
        file=repo_path,
        line=line,
        span=span,
        signal_kind="bottom",
        strict_score_eligible=strict,
        source_position_basis=basis,
        provenance_classification=classification,
        provenance=provenance,
    )


def _parse_bottom_row(raw: Any) -> tuple[
    int | None,
    tuple[int, int] | None,
    SourcePositionBasis,
    list[str] | None,
    dict[str, Any],
]:
    if raw is None:
        return None, None, "rowless", ["bottom"], {}
    if isinstance(raw, int):
        return raw, (raw, raw), "direct-node", ["bottom"], {"raw_bottom_row": raw}
    if isinstance(raw, dict):
        line = raw.get("line", raw.get("row", raw.get("lineno")))
        if line is not None:
            line = int(line)
        start = raw.get("start", line)
        end = raw.get("end", line)
        span = (int(start), int(end)) if start is not None and end is not None else None
        basis = raw.get("source_position_basis", raw.get("basis", "direct-node"))
        if basis not in {
            "direct-node",
            "defining-expr",
            "enclosing-function",
            "rowless",
            "unknown",
        }:
            basis = "unknown"
        facts = raw.get("facts_used")
        if facts is not None and not isinstance(facts, list):
            facts = [str(facts)]
        provenance = {
            key: value
            for key, value in raw.items()
            if key
            not in {
                "line",
                "row",
                "lineno",
                "start",
                "end",
                "source_position_basis",
                "basis",
                "facts_used",
            }
        }
        return line, span, basis, facts or ["bottom"], provenance
    return None, None, "unknown", ["bottom"], {"raw_bottom_row": raw}
