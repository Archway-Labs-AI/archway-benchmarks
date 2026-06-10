"""Engine-side BugsInPy detection driver — runs INSIDE the pinned Archway hatch
env (`hatch run python scripts/bugsinpy_analyze_driver.py <manifest> <out>` with
cwd = the pinned read-only worktree). Stdlib + `sd_core` ONLY (no archway_benchmarks
import — different venv). READ-ONLY: imports the pinned engine, never edits it.

The honest line-level flag predicate
------------------------------------
The engine is a type/abstract-value analyzer, not a bug detector. The ONLY
location-bearing "the engine surfaced an anomaly here" signal it emits is a
`bottom` (uninhabited / unreachable) lattice element attached to a binding's
`source_position`. So a FLAG = a source row where some binding's element is
`{"kind": "bottom"}`. We deliberately do NOT count `top` ("unknown / gave up"),
which is everywhere the engine is imprecise — counting it would be dishonest
inflation. Whole-file translate/analyze FAILURE is NOT a flag (it happens on
buggy AND fixed code); it is recorded separately as the coverage weakness.

Per file we stage the pipeline so the weakness can be attributed:
  parse_error    — not even valid Python at this commit (environmental)
  translate_error/translate_empty — engine can't translate the construct
  analyze_error  — translated but analysis raised (e.g. FixpointError)
  analyze_timeout— analysis exceeded the per-file budget (pathological)
  analyzed       — full success; `bottom_rows` are the flags

Input manifest JSON : [{"key": "<proj:id>",
                        "files": [{"repo_path": "pkg/x.py", "local_path": "/abs/x.py"}]}]
Output JSON         : {"<proj:id>": {"<repo_path>": {status, bottom_rows, n_bindings,
                                                     n_bottom, error}}}
"""
from __future__ import annotations

import ast
import json
import signal
import sys
from pathlib import Path

from sd_core.analysis_server import analyze_source as analyze_json  # JSON /types shape
from sd_core.translate.modules import translate_module

PER_FILE_TIMEOUT_S = 15
CHECKPOINT_EVERY = 10


class _Timeout(Exception):
    pass


def _on_alarm(signum, frame):  # noqa: ARG001
    raise _Timeout()


def collect_bottom_rows(body: dict) -> tuple[set[int], int, int]:
    """Walk the FinalizedAnalysis JSON; return (bottom rows, n_bindings, n_bottom).

    Covers module bindings AND every function instantiation's params/captures/
    locals/ret — the full name→(element, position) picture the server ships.
    """
    rows: set[int] = set()
    total = 0
    bottoms = 0

    def handle_binding(bd: dict) -> None:
        nonlocal total, bottoms
        if not isinstance(bd, dict):
            return
        total += 1
        elt = bd.get("element") or {}
        if elt.get("kind") == "bottom":
            bottoms += 1
            sp = bd.get("source_position")
            if sp and sp.get("row"):
                rows.add(int(sp["row"]))

    def handle_scope(scope: dict) -> None:  # name -> [binding, ...]
        for history in (scope or {}).values():
            for bd in history or []:
                handle_binding(bd)

    handle_scope(body.get("module", {}).get("bindings", {}))
    for fv in body.get("functions", []) or []:
        for inst in fv.get("instantiations", []) or []:
            for key in ("params", "captures", "locals"):
                handle_scope(inst.get(key, {}))
            ret = inst.get("ret")
            if ret:
                handle_binding(ret)
    return rows, total, bottoms


def process_file(src: str) -> dict:
    # (a) parse — non-parseable is environmental, not an engine gap
    try:
        ast.parse(src)
    except SyntaxError as e:
        return {"status": "parse_error", "bottom_rows": [], "n_bindings": 0,
                "n_bottom": 0, "error": f"SyntaxError: {str(e)[:200]}"}
    # (b) translate
    try:
        res = translate_module(src)
        if getattr(res, "morphism", None) is None:
            return {"status": "translate_empty", "bottom_rows": [], "n_bindings": 0,
                    "n_bottom": 0, "error": "no morphism"}
    except _Timeout:
        raise
    except BaseException as e:  # NotImplementedError/ValueError/... — engine gap
        return {"status": "translate_error", "bottom_rows": [], "n_bindings": 0,
                "n_bottom": 0, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    # (c) analyze + finalize (JSON projection, elements already serialized)
    try:
        body = analyze_json(src, "main")
    except _Timeout:
        raise
    except BaseException as e:  # FixpointError/... — engine gap
        return {"status": "analyze_error", "bottom_rows": [], "n_bindings": 0,
                "n_bottom": 0, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    rows, total, bottoms = collect_bottom_rows(body)
    return {"status": "analyzed", "bottom_rows": sorted(rows), "n_bindings": total,
            "n_bottom": bottoms, "error": None}


def run(manifest_path: str, out_path: str) -> None:
    manifest = json.loads(Path(manifest_path).read_text())
    signal.signal(signal.SIGALRM, _on_alarm)
    # Resume: reuse any already-computed bug results from a prior (partial) run.
    out: dict[str, dict] = {}
    if Path(out_path).exists():
        try:
            out = json.loads(Path(out_path).read_text())
            print(f"[driver] resuming — {len(out)} bugs already done", file=sys.stderr, flush=True)
        except (OSError, json.JSONDecodeError):
            out = {}
    n_bugs = len(manifest)
    for i, bug in enumerate(manifest, 1):
        key = bug["key"]
        if key in out:  # already computed in a prior run
            continue
        per_file: dict[str, dict] = {}
        for f in bug["files"]:
            repo_path = f["repo_path"]
            local = f.get("local_path")
            if not local or not Path(local).is_file():
                per_file[repo_path] = {"status": "fetch_missing", "bottom_rows": [],
                                       "n_bindings": 0, "n_bottom": 0,
                                       "error": f.get("fetch_status", "no local file")}
                continue
            try:
                src = Path(local).read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                per_file[repo_path] = {"status": "read_error", "bottom_rows": [],
                                       "n_bindings": 0, "n_bottom": 0, "error": str(e)}
                continue
            signal.alarm(PER_FILE_TIMEOUT_S)
            try:
                per_file[repo_path] = process_file(src)
            except _Timeout:
                per_file[repo_path] = {"status": "analyze_timeout", "bottom_rows": [],
                                       "n_bindings": 0, "n_bottom": 0,
                                       "error": f"timeout>{PER_FILE_TIMEOUT_S}s"}
            finally:
                signal.alarm(0)
        out[key] = per_file
        # checkpoint to disk so a long run never loses progress / is resumable
        if i % CHECKPOINT_EVERY == 0 or i == n_bugs:
            Path(out_path).write_text(json.dumps(out, indent=2))
        if i % 20 == 0 or i == n_bugs:
            print(f"[driver] {i}/{n_bugs} bugs processed ({len(out)} total results)",
                  file=sys.stderr, flush=True)
    Path(out_path).write_text(json.dumps(out, indent=2))
    print(f"[driver] wrote {out_path} ({len(out)} bugs)", file=sys.stderr, flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: bugsinpy_analyze_driver.py <manifest.json> <out.json>", file=sys.stderr)
        sys.exit(2)
    run(sys.argv[1], sys.argv[2])
