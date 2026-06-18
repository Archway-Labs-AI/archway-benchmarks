#!/usr/bin/env python3
"""Before/after harness for the `self.X` / class-attr adapter-projection fix.

Two phases, deliberately split so the before/after differ ONLY by adapter code:

  fetch  — hit the live Archway analysis server (real production HTTP path via
           ArchwayAnalysisEngine) for every `classes` snippet and cache the raw
           FinalizedAnalysis JSON to artifacts/engine_classes.json. This is the
           "engine genuinely emits these bindings" evidence; it is captured once
           and never depends on the adapter.

  score  — load the cached engine JSON, rebuild ArchwayAnalysisResult per
           snippet, run the REAL adapter + REAL scorer, and write per-family
           outcome counts to the `--out` file. Run it once before the adapter
           edit and once after; the cached engine JSON is identical across both,
           so any delta is purely the adapter change.

Usage:
  python harness.py fetch
  python harness.py score --out artifacts/score_before.json
  (edit adapter)
  python harness.py score --out artifacts/score_after.json
"""
# ruff: noqa: E402, I001  -- sys.path is set up before the first-party imports
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from archway_benchmarks.benchmarks.typeevalpy import (  # noqa: E402
    TypeEvalPyAutogenBenchmark,
    _location_to_record,
)
from archway_benchmarks.engines.archway import (  # noqa: E402
    ArchwayAnalysisEngine,
    ArchwayAnalysisResult,
    ArchwayTranslationEngine,
)
from archway_benchmarks.benchmarks.archway_adapter import (  # noqa: E402
    ArchwayAnalysisResultAdapter,
)
from archway_benchmarks.scoring.typeevalpy import score_snippet  # noqa: E402
from archway_benchmarks.outcome import Outcome  # noqa: E402

CORPUS = REPO / "extras/TypeEvalPy/autogen_typeevalpy_benchmark/python_features"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ENGINE_CACHE = ARTIFACTS / "engine_classes.json"
SERVER = "http://127.0.0.1:8788"


def _family(suite_path: str) -> str:
    # suite_path like "classes/base_class_calls_child_1_1_int_float"
    leaf = suite_path.split("/", 1)[1]
    return re.sub(r"_\d.*$", "", leaf)


def _classes_snippets():
    bench = TypeEvalPyAutogenBenchmark(corpus_root=CORPUS)
    return [s for s in bench.load() if s.suite_path.startswith("classes/")]


def fetch() -> None:
    snippets = _classes_snippets()
    translator = ArchwayTranslationEngine()
    engine = ArchwayAnalysisEngine(server_url=SERVER, corpus_root=CORPUS)
    out: dict[str, dict] = {}
    errors = 0
    for i, snip in enumerate(snippets, 1):
        tr = translator.translate(snip.source, snip.file_path)
        res = engine.analyze(tr)
        out[snip.suite_path] = {
            "module_bindings": res.module_bindings,
            "functions": list(res.functions),
            "module_name": res.module_name,
            "error": res.error,
        }
        if res.error:
            errors += 1
        if i % 50 == 0:
            print(f"  fetched {i}/{len(snippets)} (errors so far: {errors})")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    ENGINE_CACHE.write_text(json.dumps(out, indent=0))
    print(f"wrote {ENGINE_CACHE} : {len(out)} snippets, {errors} engine errors")


def score(out_path: str) -> None:
    cache = json.loads(ENGINE_CACHE.read_text())
    snippets = {s.suite_path: s for s in _classes_snippets()}
    adapter = ArchwayAnalysisResultAdapter()

    # family -> outcome -> count
    by_family: dict[str, dict[str, int]] = {}
    # family -> list of (suite_path, gt_name, outcome) for flipped/notable cases
    detail: dict[str, list] = {}

    for suite_path, snip in snippets.items():
        rec = cache.get(suite_path)
        if rec is None:
            continue
        result = ArchwayAnalysisResult(
            snippet_path=snip.file_path,
            module_bindings=rec["module_bindings"] or {},
            functions=tuple(rec["functions"] or []),
            module_name=rec["module_name"],
            error=rec["error"],
        )
        anns = adapter.to_annotations(result, snip)
        preds = {a.location: a.types for a in anns}
        gt = {a.location: a.types for a in snip.annotations}
        scored = score_snippet(suite_path, gt, preds, _location_to_record)

        fam = _family(suite_path)
        fb = by_family.setdefault(fam, {o.value: 0 for o in Outcome})
        for o in scored.outcomes:
            fb[o.outcome.value] += 1
            detail.setdefault(fam, []).append(
                {
                    "suite": suite_path,
                    "name": o.location.name,
                    "line": o.location.line,
                    "col": o.location.col,
                    "outcome": o.outcome.value,
                    "expected": sorted(o.expected_types),
                    "predicted": sorted(o.predicted_types) if o.predicted_types else None,
                }
            )

    totals = {o.value: 0 for o in Outcome}
    for fb in by_family.values():
        for k, v in fb.items():
            totals[k] += v

    payload = {"totals": totals, "by_family": by_family, "detail": detail}
    Path(out_path).write_text(json.dumps(payload, indent=2))
    print(f"wrote {out_path}")
    print("TOTALS:", totals)
    print(f"{'family':32} EXACT  TYPE_MISS  LOC_MISS  SPURIOUS")
    for fam in sorted(by_family):
        fb = by_family[fam]
        print(f"{fam:32} {fb['EXACT']:5}  {fb['TYPE_MISS']:9}  {fb['LOCATION_MISS']:8}  {fb['SPURIOUS']:8}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    sp = sub.add_parser("score")
    sp.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.cmd == "fetch":
        fetch()
    else:
        score(args.out)


if __name__ == "__main__":
    main()
