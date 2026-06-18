#!/usr/bin/env python3
"""Before/after harness for the subscript dict/list value-projection adapter fix.

Same two-phase shape as ``harness.py`` (the self-attr harness), deliberately
split so the before/after differ ONLY by adapter code:

  fetch  — hit the live Archway analysis server (real production HTTP path via
           ArchwayAnalysisEngine) for every ``dicts/`` and ``lists/`` snippet
           and cache the raw FinalizedAnalysis JSON to
           artifacts/engine_dicts_lists.json. This is the "engine genuinely
           emits these slots" evidence; captured once, never depends on the
           adapter.

  score  — load the cached engine JSON, rebuild ArchwayAnalysisResult per
           snippet, run the REAL adapter + REAL scorer, and write per-bucket
           outcome counts to the ``--out`` file. Run once before the adapter
           edit and once after; the cached engine JSON is identical across
           both, so any delta is purely the adapter change.

A GT annotation is bucketed as ``subscript`` iff its name contains ``[``
(``d['a']``, ``a[0]``, ``d['a']['b']``); otherwise ``plain``.

Usage:
  python harness_subscript.py fetch
  python harness_subscript.py score --out artifacts/score_sub_before.json
  (edit adapter)
  python harness_subscript.py score --out artifacts/score_sub_after.json
"""
# ruff: noqa: E402, I001  -- sys.path is set up before the first-party imports
from __future__ import annotations

import argparse
import json
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
ENGINE_CACHE = ARTIFACTS / "engine_dicts_lists.json"
SERVER = "http://127.0.0.1:8788"
CATEGORIES = ("dicts", "lists")


def _snippets():
    bench = TypeEvalPyAutogenBenchmark(corpus_root=CORPUS)
    return [
        s
        for s in bench.load()
        if s.suite_path.split("/", 1)[0] in CATEGORIES
    ]


def fetch() -> None:
    snippets = _snippets()
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
        if i % 100 == 0:
            print(f"  fetched {i}/{len(snippets)} (errors so far: {errors})")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    ENGINE_CACHE.write_text(json.dumps(out, indent=0))
    print(f"wrote {ENGINE_CACHE} : {len(out)} snippets, {errors} engine errors")


def _is_subscript(name: str | None) -> bool:
    return bool(name) and "[" in name


def score(out_path: str) -> None:
    cache = json.loads(ENGINE_CACHE.read_text())
    snippets = {s.suite_path: s for s in _snippets()}
    adapter = ArchwayAnalysisResultAdapter()

    # category -> bucket -> outcome -> count
    by_cat_bucket: dict[str, dict[str, dict[str, int]]] = {}
    # subscript-GT detail (every subscript GT outcome) for the flip audit
    sub_detail: list[dict] = []

    def _empty():
        return {o.value: 0 for o in Outcome}

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

        cat = suite_path.split("/", 1)[0]
        cb = by_cat_bucket.setdefault(cat, {})
        for o in scored.outcomes:
            bucket = "subscript" if _is_subscript(o.location.name) else "plain"
            cb.setdefault(bucket, _empty())[o.outcome.value] += 1
            if bucket == "subscript":
                sub_detail.append(
                    {
                        "suite": suite_path,
                        "name": o.location.name,
                        "line": o.location.line,
                        "col": o.location.col,
                        "outcome": o.outcome.value,
                        "expected": sorted(o.expected_types),
                        "predicted": sorted(o.predicted_types)
                        if o.predicted_types
                        else None,
                    }
                )

    # roll-ups
    totals = _empty()
    bucket_totals: dict[str, dict[str, int]] = {}
    for cat, cb in by_cat_bucket.items():
        for bucket, ob in cb.items():
            bt = bucket_totals.setdefault(bucket, _empty())
            for k, v in ob.items():
                bt[k] += v
                totals[k] += v

    payload = {
        "totals": totals,
        "bucket_totals": bucket_totals,
        "by_cat_bucket": by_cat_bucket,
        "subscript_detail": sub_detail,
    }
    Path(out_path).write_text(json.dumps(payload, indent=2))
    print(f"wrote {out_path}")
    print("TOTALS:", totals)
    for bucket in ("subscript", "plain"):
        bt = bucket_totals.get(bucket)
        if bt:
            print(
                f"  {bucket:10} EXACT={bt['EXACT']:5} "
                f"TYPE_MISS={bt['TYPE_MISS']:5} "
                f"LOC_MISS={bt['LOCATION_MISS']:5} "
                f"SPURIOUS={bt['SPURIOUS']:4}"
            )


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
