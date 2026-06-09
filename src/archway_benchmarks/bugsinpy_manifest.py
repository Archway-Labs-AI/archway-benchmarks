"""BugsInPy corpus manifest — per-bug metadata, parallel to `manifest.py`.

Exposes, for every bug, the fix-shape facts a LATER pre-classification pass
needs to subset by bug shape: project, files touched, lines changed, number of
failing tests, python version, buggy/fixed commits. This module deliberately
does NOT classify bugs, decide tractability, or run anything — it only surfaces
metadata. Classification is Ben's separate manual-validation pass.

Regenerate with:  `archway-bench bugsinpy-manifest`
(or `python -m archway_benchmarks.bugsinpy_manifest`).
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark


@dataclass(frozen=True)
class BugManifestRecord:
    project: str
    bug_id: str
    key: str
    buggy_commit: str
    fixed_commit: str
    python_version: str | None
    n_files_touched: int
    files_touched: list[str]
    lines_changed: int
    n_failing_tests: int
    failing_tests: list[str]
    # bug-location shape (patch-derived); NOT a tractability judgment
    single_file: bool
    single_hunk_region: bool
    gt_locations: list[dict[str, Any]]


@dataclass
class BugManifest:
    benchmark: str
    corpus_commit: str | None
    total_bugs: int
    projects: dict[str, int] = field(default_factory=dict)
    bugs: list[BugManifestRecord] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        single_file = sum(1 for b in self.bugs if b.single_file)
        return {
            "total_bugs": self.total_bugs,
            "n_projects": len(self.projects),
            "single_file_bugs": single_file,
            "multi_file_bugs": self.total_bugs - single_file,
            "bugs_per_project": dict(sorted(self.projects.items())),
        }


def generate(benchmark: BugsInPyBenchmark | None = None) -> BugManifest:
    bench = benchmark or BugsInPyBenchmark()
    bugs = bench.load()
    manifest = BugManifest(
        benchmark=bench.name,
        corpus_commit=bench.corpus_commit(),
        total_bugs=len(bugs),
    )
    for b in bugs:
        manifest.projects[b.project] = manifest.projects.get(b.project, 0) + 1
        manifest.bugs.append(BugManifestRecord(
            project=b.project,
            bug_id=b.bug_id,
            key=b.key,
            buggy_commit=b.buggy_commit,
            fixed_commit=b.fixed_commit,
            python_version=b.python_version,
            n_files_touched=b.n_files_touched,
            files_touched=list(b.files_touched),
            lines_changed=b.lines_changed,
            n_failing_tests=len(b.failing_tests),
            failing_tests=list(b.failing_tests),
            single_file=(b.n_files_touched == 1),
            single_hunk_region=(len(b.bug_locations) == 1),
            gt_locations=[
                {"file": loc.file, "start": loc.start, "end": loc.end, "lines": sorted(loc.lines)}
                for loc in b.bug_locations
            ],
        ))
    return manifest


def write(manifest: BugManifest, path: Path) -> None:
    payload = {
        "benchmark": manifest.benchmark,
        "corpus_commit": manifest.corpus_commit,
        "total_bugs": manifest.total_bugs,
        "summary": manifest.summary(),
        "bugs": [asdict(b) for b in manifest.bugs],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _cli(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="archway-bench-bugsinpy-manifest")
    parser.add_argument("--output", "-o", default="bugsinpy_manifest.json")
    parser.add_argument("--corpus", default=None, help="Override the corpus root")
    args = parser.parse_args(argv)

    bench = BugsInPyBenchmark(corpus_root=Path(args.corpus) if args.corpus else None)
    manifest = generate(bench)
    out = Path(args.output)
    write(manifest, out)
    s = manifest.summary()
    print(f"Wrote {out}")
    print(f"  {s['total_bugs']} bugs across {s['n_projects']} projects")
    print(f"  single-file: {s['single_file_bugs']} · multi-file: {s['multi_file_bugs']}")
    print("  (metadata only — no classification, no tractability judgment)")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
