"""BugsInPy CLI surface — registered into the main `archway-bench` parser.

Kept in its own module so the BugsInPy machinery slots in alongside TypeEvalPy
without bloating `cli.py`. `register(sub)` adds the `bugsinpy-*` subcommands;
`dispatch(args)` handles them (returning None for non-BugsInPy commands).

Commands (machinery — invokable, but this task runs none):
  bugsinpy-manifest    dump per-bug metadata (for a later classification pass)
  bugsinpy-detect      score a tool's flagged locations (Track 1 / detection)
  bugsinpy-repair      run candidate fixes' failing tests + score (Track 2 / repair)
  bugsinpy-progress    render the BugsInPy progress report

How a FUTURE run is invoked (no run happens here):
  # detection on a declared subset:
  archway-bench bugsinpy-detect --flagged flags.json \
      --subset-project black pandas --engine-sha <sha> --corpus-commit <sha>
  # repair on a declared subset, via the BugsInPy framework runner:
  archway-bench bugsinpy-repair --fixes fixes.json --runner framework \
      --subset-key black:1 black:3 --engine-sha <sha> --corpus-commit <sha>

  flags.json : {"black:1": [{"file": "src/black.py", "lines": [120, 121]}], ...}
  fixes.json : {"black:1": "<unified diff to apply to the buggy checkout>", ...}
"""
from __future__ import annotations

import json
from pathlib import Path


def register(sub) -> None:
    pm = sub.add_parser("bugsinpy-manifest", help="Dump BugsInPy per-bug metadata (no classification).")
    pm.add_argument("--output", "-o", default="bugsinpy_manifest.json")
    pm.add_argument("--corpus", default=None, help="Override the BugsInPy corpus root.")

    common = []
    for name, help_ in [("bugsinpy-detect", "Score flagged locations against bug GT (detection mode)."),
                        ("bugsinpy-repair", "Run candidate fixes' failing tests + score (repair mode).")]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--corpus", default=None)
        p.add_argument("--db", default="runs.db")
        p.add_argument("--notes", default=None)
        p.add_argument("--engine-sha", default=None, help="Provenance: the engine SHA under test.")
        p.add_argument("--corpus-commit", default=None,
                       help="Provenance: the BugsInPy corpus commit (default: resolved from the submodule).")
        p.add_argument("--subset-project", nargs="+", default=None, help="Declared subset: these projects only.")
        p.add_argument("--subset-key", nargs="+", default=None, help="Declared subset: these project:bug_id keys only.")
        common.append(p)
    common[0].add_argument("--flagged", required=True, help="JSON: {bug_key: [{file, lines:[...]}]}.")
    common[0].add_argument("--line-tolerance", type=int, default=0, help="Widen GT line match by ±N lines.")
    common[1].add_argument("--fixes", required=True, help="JSON: {bug_key: unified-diff patch}.")
    common[1].add_argument("--runner", choices=["framework", "stub"], default="framework")

    pp = sub.add_parser("bugsinpy-progress", help="Render the BugsInPy progress report.")
    pp.add_argument("--db", default="runs.db")
    pp.add_argument("--out-md", default="bugsinpy_progress.md")
    pp.add_argument("--mode", choices=["detection", "repair"], default=None)


def dispatch(args) -> int | None:
    cmd = getattr(args, "cmd", None)
    if cmd == "bugsinpy-manifest":
        return _cmd_manifest(args)
    if cmd == "bugsinpy-detect":
        return _cmd_detect(args)
    if cmd == "bugsinpy-repair":
        return _cmd_repair(args)
    if cmd == "bugsinpy-progress":
        return _cmd_progress(args)
    return None


# ----- handlers -----

def _bench(args):
    from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark
    return BugsInPyBenchmark(corpus_root=Path(args.corpus) if args.corpus else None)


def _subset(args, bench):
    """Resolve the declared subset to a set of bug keys, or None for full corpus."""
    if not args.subset_project and not args.subset_key:
        return None, "all"
    bugs = bench.subset(projects=args.subset_project, bug_keys=args.subset_key)
    keys = {b.key for b in bugs}
    return keys, sorted(keys)


def _cmd_manifest(args) -> int:
    from archway_benchmarks import bugsinpy_manifest
    bench = _bench(args)
    manifest = bugsinpy_manifest.generate(bench)
    bugsinpy_manifest.write(manifest, Path(args.output))
    s = manifest.summary()
    print(f"Wrote {args.output}: {s['total_bugs']} bugs / {s['n_projects']} projects "
          f"(single-file {s['single_file_bugs']}). Metadata only — no classification.")
    return 0


def _record_common(conn, args, mode: str, bench, subset_desc):
    from archway_benchmarks.store import create_run
    metadata = {
        "mode": mode,
        "engine_sha": args.engine_sha,
        "corpus_commit": args.corpus_commit or bench.corpus_commit(),
        "subset": subset_desc,
    }
    return create_run(conn, benchmark="bugsinpy", engine=f"bugsinpy-{mode}",
                      stub_accuracy=None, seed=None, notes=args.notes, metadata=metadata)


def _cmd_detect(args) -> int:
    from archway_benchmarks.bugsinpy_types import BugLocation
    from archway_benchmarks.scoring.bugsinpy import score_detection
    from archway_benchmarks.store import (connect, record_bugsinpy_detection,
                                          record_bugsinpy_scores)

    bench = _bench(args)
    subset_keys, subset_desc = _subset(args, bench)
    raw = json.loads(Path(args.flagged).read_text())
    flagged = {
        key: [BugLocation(file=f["file"], start=min(f.get("lines") or [f.get("start", 0)]),
                          end=max(f.get("lines") or [f.get("end", 0)]),
                          lines=frozenset(f.get("lines") or []))
              for f in locs]
        for key, locs in raw.items()
    }
    scores, outcomes = score_detection(bench, flagged, subset=subset_keys,
                                       line_tolerance=args.line_tolerance)
    scope = "subset" if subset_keys is not None else "all"
    with connect(Path(args.db)) as conn:
        run_id = _record_common(conn, args, "detection", bench, subset_desc)
        record_bugsinpy_detection(conn, run_id, outcomes)
        record_bugsinpy_scores(conn, run_id, mode="detection", scope=scope, scores=scores)
    print(f"run #{run_id}: detection {scores.detected}/{scores.total_bugs} "
          f"({scores.detection_rate:.1%}) · scope {scope} · engine_sha {args.engine_sha}")
    return 0


def _cmd_repair(args) -> int:
    from archway_benchmarks.engines.bugsinpy import (BugsInPyTestRunner, CandidateFix,
                                                    StubTestRunner)
    from archway_benchmarks.scoring.bugsinpy import score_repair
    from archway_benchmarks.store import (connect, record_bugsinpy_repair,
                                          record_bugsinpy_scores)

    bench = _bench(args)
    subset_keys, subset_desc = _subset(args, bench)
    fixes = json.loads(Path(args.fixes).read_text())
    if args.runner == "stub":
        runner = StubTestRunner(repaired_keys=set(fixes.keys()))
    else:
        runner = BugsInPyTestRunner(corpus_root=bench.corpus_root)

    bugs = bench.subset(bug_keys=list(subset_keys)) if subset_keys is not None else bench.load()
    outcomes = {}
    for bug in bugs:
        if bug.key not in fixes:
            continue
        outcomes[bug.key] = runner.run_failing_tests(bug, CandidateFix(bug.key, fixes[bug.key]))
    scores, ordered = score_repair(bench, outcomes, subset=subset_keys)
    scope = "subset" if subset_keys is not None else "all"
    with connect(Path(args.db)) as conn:
        run_id = _record_common(conn, args, "repair", bench, subset_desc)
        record_bugsinpy_repair(conn, run_id, ordered)
        record_bugsinpy_scores(conn, run_id, mode="repair", scope=scope, scores=scores)
    print(f"run #{run_id}: repair {scores.repaired}/{scores.total_bugs} "
          f"({scores.repair_rate:.1%}) · scope {scope} · runner {args.runner}")
    return 0


def _cmd_progress(args) -> int:
    from archway_benchmarks import bugsinpy_report
    out = bugsinpy_report.write_progress(Path(args.db), args.out_md, mode=args.mode)
    print(f"wrote {out}")
    return 0
