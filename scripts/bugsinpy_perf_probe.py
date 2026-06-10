"""Read-only translate/analyze perf probe (BugsInPy detection workstream).

Substantiates whether a `translate_error -> timeout` transition (seen when an engine
build clears a fast-failing translate error) is a *translate-stage* perf wall
(hang or slow error) versus a *slow-but-finite analysis* that a bigger driver budget
would convert to coverage. Read-only against the pinned engine — runs translate/analyze,
edits nothing.

Per file it runs `translate_module` then (if that finishes) `analyze_source`, each under
a SIGALRM budget, and classifies the outcome. On a translate-stage error it also dumps
the top sd_core traceback frames (a free locus hint for the perf hot path).

Usage (in the pinned read-only worktree's hatch env):
    hatch run python <repo>/scripts/bugsinpy_perf_probe.py <key> <src_path> <budget_s> <out_json>

`out_json` is read-merge-written so repeated single-key invocations accumulate
(checkpointing across a bounded batch).
"""
import json
import os
import signal
import sys
import time
import traceback

from sd_core.analysis_server import analyze_source as analyze_json
from sd_core.translate.modules import translate_module


class TO(Exception):
    pass


def _onalarm(signum, frame):
    raise TO()


def _sd_frames(exc, limit=6):
    """Top sd_core frames of the active traceback, innermost last."""
    tb = traceback.extract_tb(exc.__traceback__)
    sd = [f for f in tb if "sd_core" in (f.filename or "")]
    out = []
    for f in sd[-limit:]:
        fn = f.filename.split("sd_core/", 1)[-1]
        out.append(f"sd_core/{fn}:{f.lineno} {f.name}")
    return out


def probe(key, path, budget):
    signal.signal(signal.SIGALRM, _onalarm)
    src = open(path, encoding="utf-8", errors="replace").read()
    res = {"key": key, "path": path, "size_kb": round(len(src) / 1024, 1), "budget_s": budget}

    t0 = time.perf_counter()
    try:
        signal.alarm(budget)
        m = translate_module(src)
        signal.alarm(0)
        t_tr = time.perf_counter() - t0
    except TO:
        signal.alarm(0)
        res.update(stage="translate", outcome="HANG",
                   detail=f"translate did not finish in {budget}s",
                   translate_s=round(time.perf_counter() - t0, 1))
        return res
    except BaseException as e:
        signal.alarm(0)
        res.update(stage="translate", outcome="ERROR",
                   error=f"{type(e).__name__}: {str(e)[:120]}",
                   translate_s=round(time.perf_counter() - t0, 1),
                   sd_frames=_sd_frames(e))
        return res

    # translate finished — now analysis
    t1 = time.perf_counter()
    try:
        signal.alarm(budget)
        analyze_json(src, "main")
        signal.alarm(0)
        res.update(stage="analyze", outcome="ANALYZED",
                   translate_s=round(t_tr, 1),
                   analyze_s=round(time.perf_counter() - t1, 1),
                   note="SLOW-BUT-FINITE: translate finished; analysis completed within budget "
                        "(bigger driver budget WOULD recover this -> NOT a translate-perf wall)")
        return res
    except TO:
        signal.alarm(0)
        res.update(stage="analyze", outcome="HANG",
                   translate_s=round(t_tr, 1),
                   detail=f"translate finished in {t_tr:.1f}s but analysis did not finish in {budget}s",
                   note="ANALYSIS pathological (translate is fine) -> a translate-perf claim does NOT hold here")
        return res
    except BaseException as e:
        signal.alarm(0)
        res.update(stage="analyze", outcome="ERROR",
                   translate_s=round(t_tr, 1),
                   analyze_s=round(time.perf_counter() - t1, 1),
                   error=f"{type(e).__name__}: {str(e)[:120]}",
                   sd_frames=_sd_frames(e),
                   note="translate finished; analysis errored -> NOT a translate-perf wall")
        return res


def main():
    key, path, budget, out_json = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    res = probe(key, path, budget)
    acc = {}
    if os.path.exists(out_json):
        try:
            acc = json.load(open(out_json))
        except Exception:
            acc = {}
    acc[key] = res
    json.dump(acc, open(out_json, "w"), indent=2)
    print(f"{key}: stage={res.get('stage')} outcome={res.get('outcome')} "
          f"translate_s={res.get('translate_s')} "
          f"{res.get('error') or res.get('detail') or res.get('note','')[:60]}")


if __name__ == "__main__":
    main()
