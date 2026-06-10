"""READ-ONLY localize probe — run INSIDE the pinned Archway hatch env, cwd = the
pinned read-only worktree. For each candidate file it reproduces the engine crash
and records the DEEPEST sd_core frame (file:line:func) plus the full engine-frame
stack tail. Pure diagnostics: imports the pinned engine, never edits it.

Input  : JSON list [{"family","key","repo_path","local_path"}]
Output : JSON {key::repo_path: {family, status, exc, deepest_engine_frame, engine_stack_tail}}
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from sd_core.translate.modules import translate_module
from sd_core.analysis_server import analyze_source as analyze_json


def _engine_frames(tb) -> list[str]:
    frames = []
    for fr in traceback.extract_tb(tb):
        fn = fr.filename
        if "sd_core" in fn:
            short = fn.split("sd_core/", 1)[1] if "sd_core/" in fn else Path(fn).name
            frames.append(f"sd_core/{short}:{fr.lineno} {fr.name}")
    return frames


def probe(local_path: str) -> dict:
    src = Path(local_path).read_text(encoding="utf-8", errors="replace")
    # translate
    try:
        res = translate_module(src)
    except BaseException as e:  # noqa: BLE001
        frames = _engine_frames(e.__traceback__)
        return {"status": "translate_error", "exc": f"{type(e).__name__}: {str(e)[:160]}",
                "deepest_engine_frame": frames[-1] if frames else None,
                "engine_stack_tail": frames[-6:]}
    if getattr(res, "morphism", None) is None:
        return {"status": "translate_empty", "exc": "no morphism",
                "deepest_engine_frame": None, "engine_stack_tail": []}
    # analyze
    try:
        analyze_json(src, "main")
    except BaseException as e:  # noqa: BLE001
        frames = _engine_frames(e.__traceback__)
        return {"status": "analyze_error", "exc": f"{type(e).__name__}: {str(e)[:160]}",
                "deepest_engine_frame": frames[-1] if frames else None,
                "engine_stack_tail": frames[-6:]}
    return {"status": "analyzed", "exc": None, "deepest_engine_frame": None,
            "engine_stack_tail": []}


def main(cand_path: str, out_path: str) -> int:
    cands = json.loads(Path(cand_path).read_text())
    out = {}
    for c in cands:
        k = f"{c['key']}::{c['repo_path']}"
        try:
            r = probe(c["local_path"])
        except Exception as e:  # noqa: BLE001
            r = {"status": "probe_error", "exc": str(e)[:160],
                 "deepest_engine_frame": None, "engine_stack_tail": []}
        r["family"] = c["family"]
        out[k] = r
        print(f"[{c['family']:20}] {k}\n    {r['status']}: {r['exc']}\n    deepest: {r['deepest_engine_frame']}",
              file=sys.stderr, flush=True)
    Path(out_path).write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
