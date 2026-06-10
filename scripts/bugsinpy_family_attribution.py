"""Family attribution for a BugsInPy detection run — sole/present per failure family.

Refreshes the ranked engine-fix plan's gain columns from a driver results file.
For every bug it classifies each patch-touched file's failure into a coarse
FAMILY, then per INFEASIBLE bug (no ground-truth file analyzed) computes:

  present(family) — the bug has >=1 touched file failing with this family
                    (necessary-for-load, not sufficient; strict upper bound).
  sole(family)    — this family is the ONLY distinct blocker across all the bug's
                    non-analyzed touched files (necessary and, for these, the only
                    translator wall — upper-bounds the LOAD/coverage gain).

Pure benchmarks-side: reads the loader GT + driver results + fetch manifest; reads
NO engine code. Honest: sole/present are UPPER BOUNDS on coverage, not detection.

usage: bugsinpy_family_attribution.py <manifest.json> <results.json> <out.json>
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark


def classify(status: str, error: str | None) -> str | None:
    """Map a per-file (status, error) to a coarse failure family name.

    Families mirror the engine-fix plan's taxonomy so the gain columns line up.
    `analyzed` returns None (not a blocker).
    """
    if status == "analyzed":
        return None
    err = error or ""
    if status == "analyze_timeout":
        return "timeout"
    if status == "parse_error":
        return "ENV:parse_error"
    if status in ("fetch_missing", "read_error"):
        return f"ENV:{status}"
    # translate / analyze exception families, by message signature
    if "pop from empty list" in err:
        return "pop_empty_list"
    if "permutation of source" in err or ("ambient" in err and "don't match" in err):
        return "ambient_wire"
    if status == "analyze_error" and err.startswith("KeyError") and "ambient" in err:
        return "analyze_error:ambient_keyerror"
    if status == "analyze_error" and err.startswith("RecursionError"):
        return "analyze_error:RecursionError"
    if status == "analyze_error":
        return f"analyze_error:{err.split(':',1)[0]}"
    if "no handler for Slice" in err:
        return "slice"
    if "Attribute target not in last position" in err:
        return "chained_assign"
    if "'NoneType' object has no attribute 'return_wire'" in err:
        return "nonetype_return_wire"
    if "'Attribute' object has no attribute 'id'" in err:
        return "attribute_no_id"
    if "list index out of range" in err:
        return "list_index"
    if "tuple index out of range" in err:
        return "tuple_index"
    if "_just_loop_exit_kinds" in err:
        return "just_loop_exit"
    if "import *" in err or ("NotImplementedError" in err and "import" in err.lower()):
        return "import_star"
    if err.startswith("RecursionError"):
        return "recursion"
    # fallback: exception type + short head
    head = err.split(":", 1)[0]
    return f"OTHER:{head}"


# rough class label for each family (informational only)
CLASS = {
    "pop_empty_list": "ENGINE(translator)",
    "ambient_wire": "ENGINE(translator)",
    "analyze_error:ambient_keyerror": "ENGINE(analysis)",
    "nonetype_return_wire": "ENGINE(translator)",
    "slice": "ENGINE(translator)",
    "list_index": "ENGINE(translator)",
    "tuple_index": "ENGINE(translator)",
    "chained_assign": "ENGINE(translator)",
    "attribute_no_id": "ENGINE(translator)",
    "just_loop_exit": "ENGINE(translator)",
    "import_star": "ENGINE(translator)",
    "recursion": "ENGINE(translator)",
    "analyze_error:RecursionError": "ENGINE(analysis)",
    "timeout": "NON-ENGINE(driver budget) / ENGINE(perf)",
    "ENV:parse_error": "ENV",
    "ENV:fetch_missing": "ENV",
    "ENV:read_error": "ENV",
}


def main(manifest_path: str, results_path: str, out_json: str) -> int:
    bench = BugsInPyBenchmark()
    bugs = {b.key: b for b in bench.load()}
    results = json.loads(Path(results_path).read_text())

    feasible = 0
    infeasible = 0
    present: dict[str, int] = defaultdict(int)
    sole: dict[str, int] = defaultdict(int)
    sole_examples: dict[str, list] = defaultdict(list)

    for key, bug in bugs.items():
        res = results.get(key, {})
        if not res:
            continue
        gt_files = {loc.file for loc in bug.bug_locations}
        gt_loaded = any(
            res.get(rp, {}).get("status") == "analyzed" for rp in gt_files if rp in res
        )
        if gt_loaded:
            feasible += 1
            continue
        infeasible += 1
        # blockers = distinct families over non-analyzed touched files
        blockers: set[str] = set()
        for r in res.values():
            fam = classify(r.get("status"), r.get("error"))
            if fam is not None:
                blockers.add(fam)
        for fam in blockers:
            present[fam] += 1
        if len(blockers) == 1:
            fam = next(iter(blockers))
            sole[fam] += 1
            if len(sole_examples[fam]) < 3:
                sole_examples[fam].append(key)

    families = sorted(
        set(present) | set(sole),
        key=lambda f: (-sole[f], -present[f]),
    )
    out = {
        "results_file": results_path,
        "feasible": feasible,
        "infeasible": infeasible,
        "families": [
            {
                "family": f,
                "sole_gated": sole.get(f, 0),
                "present": present.get(f, 0),
                "class": CLASS.get(f, "?"),
                "sole_examples": sole_examples.get(f, []),
            }
            for f in families
        ],
    }
    Path(out_json).write_text(json.dumps(out, indent=2))
    print(f"=== family attribution ({results_path}) ===")
    print(f"feasible {feasible} / infeasible {infeasible}")
    print(f"{'family':<32} {'sole':>5} {'present':>8}  class")
    for fam in families:
        print(f"{fam:<32} {sole.get(fam,0):>5} {present.get(fam,0):>8}  {CLASS.get(fam,'?')}")
    print(f"-> wrote {out_json}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: bugsinpy_family_attribution.py <manifest.json> <results.json> <out.json>",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
