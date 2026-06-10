"""Coverage + detection diagnostics for a BugsInPy detection run.

The CLI scores detection (vs GT) and joins buckets; neither produces the
COVERAGE picture — how many of the 501 bugs the engine could even load, and
WHY the rest didn't. That picture is the dominant honest finding, so this
script computes it from the fetch manifest + engine driver results + the loader's
ground truth, reusing the REAL `score_detection` so the headline numbers match
the CLI exactly.

Outputs a JSON summary (consumed when writing the DIRECTIONAL report) and prints
a human-readable digest. Pure benchmarks-side; reads no engine code.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark
from archway_benchmarks.bugsinpy_flagger import build_flags
from archway_benchmarks.scoring.bugsinpy import score_detection
from archway_benchmarks.bugsinpy_types import BugLocation


def _norm_err(status: str, err: str | None) -> str:
    """Collapse an error to a coarse reason for histogramming."""
    if not err:
        return status
    # exception type prefix + a normalized message head
    head = err.split(":", 1)[0]
    msg = err.split(":", 1)[1].strip() if ":" in err else ""
    msg = re.sub(r"0x[0-9a-fA-F]+", "0x…", msg)
    msg = re.sub(r"\d+", "N", msg)
    return f"{head}: {msg[:60]}" if msg else head


def main(manifest_path: str, results_path: str, out_json: str) -> int:
    bench = BugsInPyBenchmark()
    bugs = {b.key: b for b in bench.load()}
    manifest = json.loads(Path(manifest_path).read_text())
    results = json.loads(Path(results_path).read_text())

    flagged_raw, status = build_flags(manifest, results)
    # to BugLocation for the scorer (same shape the CLI builds)
    flagged = {
        key: [BugLocation(file=f["file"], start=min(f["lines"]), end=max(f["lines"]),
                          lines=frozenset(f["lines"])) for f in locs]
        for key, locs in flagged_raw.items()
    }

    # GT-file feasibility: a bug is "loadable" if >=1 of its GROUND-TRUTH files analyzed.
    gt_analyzed_keys: set[str] = set()
    err_hist: Counter = Counter()
    bottom_per_file: list[int] = []
    n_analyzed_files = 0
    cov_by_project_total: dict[str, int] = defaultdict(int)
    cov_by_project_loaded: dict[str, int] = defaultdict(int)
    non_py_gt = 0

    for key, bug in bugs.items():
        gt_files = {loc.file for loc in bug.bug_locations}
        res = results.get(key, {})
        cov_by_project_total[bug.project] += 1
        gt_loaded = False
        if gt_files and not any(f.endswith(".py") for f in gt_files):
            non_py_gt += 1
        for rp, r in res.items():
            st = r.get("status")
            if st == "analyzed":
                n_analyzed_files += 1
                bottom_per_file.append(r.get("n_bottom", 0))
            if st not in ("analyzed",):
                err_hist[_norm_err(st, r.get("error"))] += 1
            if rp in gt_files and st == "analyzed":
                gt_loaded = True
        if gt_loaded:
            gt_analyzed_keys.add(key)
            cov_by_project_loaded[bug.project] += 1

    # Official scores: full corpus (501 denom) AND conditional on GT-file-loaded.
    full_scores, full_outcomes = score_detection(bench, flagged, subset=None)
    cond_scores, _ = score_detection(bench, flagged, subset=gt_analyzed_keys or {"__none__"})

    detected_keys = [o.bug_key for o in full_outcomes if o.kind == "DETECTED"]
    wrong_file_keys = [o.bug_key for o in full_outcomes if o.kind == "WRONG_FILE"]

    total_bottom = sum(bottom_per_file)
    summary = {
        "total_bugs": len(bugs),
        "coverage": {
            "bugs_with_any_file_fetched": sum(
                1 for b in manifest if any(f["local_path"] for f in b["files"])),
            "bugs_analyzed_any_touched_file": status["bugs_analyzed_any"],
            "bugs_gt_file_analyzed": len(gt_analyzed_keys),
            "non_py_gt_bugs": non_py_gt,
            "file_status_counts": status["file_status_counts"],
            "by_project": {
                p: {"total": cov_by_project_total[p], "gt_loaded": cov_by_project_loaded.get(p, 0)}
                for p in sorted(cov_by_project_total)
            },
        },
        "detection_full": {
            "detected": full_scores.detected,
            "file_level": full_scores.file_level_detected,
            "attempted": full_scores.bugs_attempted,
            "total": full_scores.total_bugs,
            "rate": full_scores.detection_rate,
            "detected_keys": detected_keys,
            "wrong_file_keys": wrong_file_keys,
        },
        "detection_conditional_gt_loaded": {
            "detected": cond_scores.detected,
            "total": cond_scores.total_bugs,
            "rate": cond_scores.detection_rate,
        },
        "bottom_signal": {
            "analyzed_files": n_analyzed_files,
            "total_bottom_rows_across_files": total_bottom,
            "analyzed_files_with_any_bottom": sum(1 for n in bottom_per_file if n > 0),
            "bugs_with_any_flag": status["bugs_flagged_any"],
        },
        "top_nonload_reasons": err_hist.most_common(25),
    }
    Path(out_json).write_text(json.dumps(summary, indent=2))

    # digest
    c = summary["coverage"]
    d = summary["detection_full"]
    cd = summary["detection_conditional_gt_loaded"]
    bs = summary["bottom_signal"]
    print(f"=== BugsInPy detection summary ({summary['total_bugs']} bugs) ===")
    print(f"COVERAGE: GT-file analyzed for {c['bugs_gt_file_analyzed']}/{summary['total_bugs']} bugs "
          f"({c['bugs_gt_file_analyzed']/summary['total_bugs']:.1%}); "
          f"any touched file analyzed for {c['bugs_analyzed_any_touched_file']}.")
    print(f"DETECTION (full 501): {d['detected']} detected ({d['rate']:.2%}), "
          f"file-level {d['file_level']}, attempted {d['attempted']}.")
    print(f"DETECTION (conditional, GT-file loaded denom {cd['total']}): "
          f"{cd['detected']} ({cd['rate']:.2%}).")
    print(f"BOTTOM signal: {bs['total_bottom_rows_across_files']} bottom rows across "
          f"{bs['analyzed_files']} analyzed files; {bs['analyzed_files_with_any_bottom']} files had any.")
    print(f"DETECTED keys: {d['detected_keys']}")
    print("TOP non-load reasons:")
    for reason, n in summary["top_nonload_reasons"][:15]:
        print(f"  {n:5}  {reason}")
    print(f"-> wrote {out_json}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: bugsinpy_detect_summary.py <manifest.json> <results.json> <out.json>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
