"""Run #2 (new pin) vs run #1b (old pin) — bounded-subset comparison.

Scores detection on EXACTLY the bugs measured at the new pin (the run #2 subset),
and diffs per-file status vs run #1b on the same keys. Pure benchmarks-side; reads
no engine code. Honest: numbers are over the measured subset only, not extrapolated.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark
from archway_benchmarks.bugsinpy_flagger import build_flags
from archway_benchmarks.scoring.bugsinpy import score_detection
from archway_benchmarks.bugsinpy_types import BugLocation

OLD = "/tmp/bugsinpy_results_full_recovered.json"
NEW = "/tmp/bugsinpy_results_run2.json"
MAN = "/tmp/bugsinpy_manifest_full_recovered.json"


def main(out_json: str) -> int:
    bench = BugsInPyBenchmark()
    bugs = {b.key: b for b in bench.load()}
    manifest = json.loads(Path(MAN).read_text())
    man_by_key = {b["key"]: b for b in manifest}
    old = json.loads(Path(OLD).read_text())
    new = json.loads(Path(NEW).read_text())

    done = sorted(new)  # the run #2 measured subset
    new_man = [man_by_key[k] for k in done if k in man_by_key]

    # ---- detection on the measured subset (new pin) ----
    flagged_raw, status = build_flags(new_man, new)
    flagged = {
        key: [BugLocation(file=f["file"], start=min(f["lines"]), end=max(f["lines"]),
                          lines=frozenset(f["lines"])) for f in locs]
        for key, locs in flagged_raw.items()
    }
    scores, outcomes = score_detection(bench, flagged, subset=set(done))
    detected_keys = [o.bug_key for o in outcomes if o.kind == "DETECTED"]

    # ---- coverage on the measured subset (new pin) ----
    gt_analyzed = set()
    fam_new: Counter = Counter()
    status_counts_new: Counter = Counter()
    for key in done:
        bug = bugs.get(key)
        gt_files = {loc.file for loc in bug.bug_locations} if bug else set()
        for rp, r in new[key].items():
            st = r.get("status")
            status_counts_new[st] += 1
            if st == "analyzed" and rp in gt_files:
                gt_analyzed.add(key)
            if st != "analyzed":
                err = r.get("error") or st
                fam_new[err.split(":", 1)[0] if err else st] += 1

    # ---- per-file diff vs old pin (same keys) ----
    changes = []
    same = 0
    for key in done:
        for rp, nr in new[key].items():
            ns = nr.get("status"); ne = (nr.get("error") or "")[:80]
            o = old.get(key, {}).get(rp, {})
            os_ = o.get("status"); oe = (o.get("error") or "")[:80]
            if os_ is None:
                continue  # not in old (shouldn't happen on recovered set)
            if os_ != ns or oe != ne:
                changes.append({"key": key, "file": rp,
                                "old": f"{os_}: {oe}", "new": f"{ns}: {ne}"})
            else:
                same += 1
    # classify changes by coverage impact
    def feas(s):  # does this status make the file flag-capable?
        return s == "analyzed"
    improved = sum(1 for c in changes if not feas(c["old"].split(":")[0])
                   and feas(c["new"].split(":")[0]))
    regressed = sum(1 for c in changes if feas(c["old"].split(":")[0])
                    and not feas(c["new"].split(":")[0]))

    summary = {
        "measured_subset_size": len(done),
        "detection": {
            "detected": scores.detected,
            "file_level": scores.file_level_detected,
            "attempted": scores.bugs_attempted,
            "total_in_subset": scores.total_bugs,
            "rate": scores.detection_rate,
            "detected_keys": detected_keys,
        },
        "coverage_subset": {
            "gt_file_analyzed_bugs": len(gt_analyzed),
            "status_counts": dict(status_counts_new),
            "top_fail_families": fam_new.most_common(12),
            "bugs_with_any_flag": status["bugs_flagged_any"],
        },
        "diff_vs_old_pin": {
            "files_unchanged": same,
            "files_changed": len(changes),
            "coverage_improved_files": improved,
            "coverage_regressed_files": regressed,
            "changes": changes,
        },
    }
    Path(out_json).write_text(json.dumps(summary, indent=2))
    d = summary["detection"]; cv = summary["coverage_subset"]; df = summary["diff_vs_old_pin"]
    print(f"=== RUN #2 (pin 78e147bc) over {len(done)} measured bugs ===")
    print(f"DETECTION: {d['detected']} detected / {d['total_in_subset']} ({d['rate']:.2%}); "
          f"file-level {d['file_level']}; any-flag bugs {cv['bugs_with_any_flag']}.")
    print(f"COVERAGE(subset): GT-file analyzed for {cv['gt_file_analyzed_bugs']}/{len(done)} bugs.")
    print(f"DIFF vs old pin: {df['files_unchanged']} files unchanged, {df['files_changed']} changed "
          f"(coverage +{df['coverage_improved_files']} / -{df['coverage_regressed_files']}).")
    for c in changes[:20]:
        print(f"  Δ {c['key']} {c['file']}\n     old {c['old']}\n     new {c['new']}")
    print(f"-> wrote {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/bugsinpy_run2_compare.json"))
