"""READ-ONLY probe: is any positional metadata reachable near a `bottom` binding?
Runs INSIDE the pinned Archway hatch env (cwd = the pinned read-only worktree);
stdlib + `sd_core` ONLY. Imports the pinned engine, never edits it.

The detection flag predicate (see `bugsinpy_analyze_driver.py`) is a `bottom`
(uninhabited) lattice element attached to a binding's `source_position.row`. When a
bottom binding carries no row it cannot be attributed to a line. This probe answers,
purely from the finalized-analysis JSON: *does that JSON already carry any positional
metadata on, or beside, a rowless bottom binding?* (binding fields, sibling-scope
rows, the enclosing function's row).

For each input file this analyzes the buggy source and, for EVERY binding whose
element is `bottom`, records:
  - scope_path / name             — where the bottom lives in the scope tree
  - has_source_position, row      — does THIS binding carry a row?
  - binding_keys / element_keys   — every field the JSON ships (back-map surface)
  - source_position (raw)         — None? present-but-rowless? a real row?
  - sibling_rows_in_scope         — do OTHER bindings in the same scope carry rows?
                                    (if yes, the analyzer CAN position bindings here
                                     and the bottom is selectively rowless; if no, the
                                     whole scope is position-blind)
  - full_binding                  — the entire dict, so a human can see everything

Input  : JSON list [{"family","key","repo_path","local_path"}]
Output : JSON {key::repo_path: {status, n_bottom, bottoms:[...], sample_*_keys, ...}}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sd_core.analysis_server import analyze_source as analyze_json


def _is_bottom(bd) -> bool:
    return isinstance(bd, dict) and (bd.get("element") or {}).get("kind") == "bottom"


def _row(bd):
    sp = bd.get("source_position") if isinstance(bd, dict) else None
    return sp.get("row") if isinstance(sp, dict) else None


def _scan_scope(scope: dict, path: str, bottoms: list, fn_sp=None) -> None:
    """scope: name -> [binding, ...]. Append a record per bottom binding.

    `fn_sp` is the enclosing function value's `source_position` (None for module
    scope) — the guaranteed coarse-fallback position a D1 fix could attach.
    """
    scope = scope or {}
    rows_here = sorted({r for h in scope.values() for bd in (h or [])
                        if (r := _row(bd))})
    for name, history in scope.items():
        for i, bd in enumerate(history or []):
            if _is_bottom(bd):
                bottoms.append({
                    "scope_path": path,
                    "name": name,
                    "idx": i,
                    "has_source_position": bd.get("source_position") is not None,
                    "row": _row(bd),
                    "binding_keys": sorted(bd.keys()),
                    "element_keys": sorted((bd.get("element") or {}).keys()),
                    "source_position": bd.get("source_position"),
                    "sibling_rows_in_scope": rows_here,
                    "enclosing_fn_source_position": fn_sp,
                    "full_binding": bd,
                })


def probe_file(local_path: str) -> dict:
    src = Path(local_path).read_text(encoding="utf-8", errors="replace")
    try:
        body = analyze_json(src, "main")
    except BaseException as e:  # noqa: BLE001
        return {"status": "analyze_error", "exc": f"{type(e).__name__}: {str(e)[:200]}"}

    bottoms: list = []
    _scan_scope(body.get("module", {}).get("bindings", {}), "module.bindings", bottoms)
    for j, fv in enumerate(body.get("functions", []) or []):
        fn_sp = fv.get("source_position")
        for k, inst in enumerate(fv.get("instantiations", []) or []):
            for skey in ("params", "captures", "locals"):
                _scan_scope(inst.get(skey, {}), f"functions[{j}].inst[{k}].{skey}", bottoms, fn_sp)
            ret = inst.get("ret")
            if _is_bottom(ret):
                bottoms.append({
                    "scope_path": f"functions[{j}].inst[{k}].ret", "name": "<ret>", "idx": 0,
                    "has_source_position": ret.get("source_position") is not None,
                    "row": _row(ret), "binding_keys": sorted(ret.keys()),
                    "element_keys": sorted((ret.get("element") or {}).keys()),
                    "source_position": ret.get("source_position"),
                    "sibling_rows_in_scope": [], "enclosing_fn_source_position": fn_sp,
                    "full_binding": ret,
                })

    # Sample the keys available one level up (function value, instantiation) — these
    # are candidate back-map surfaces a fix could read a position from.
    fns = body.get("functions") or []
    sample_fn_keys = sorted(fns[0].keys()) if fns else []
    sample_inst_keys = []
    if fns and (fns[0].get("instantiations") or []):
        sample_inst_keys = sorted(fns[0]["instantiations"][0].keys())

    return {
        "status": "analyzed",
        "n_bottom": len(bottoms),
        "bottoms": bottoms,
        "n_functions": len(fns),
        "module_binding_names": sorted((body.get("module", {}).get("bindings", {}) or {}).keys()),
        "sample_function_value_keys": sample_fn_keys,
        "sample_instantiation_keys": sample_inst_keys,
    }


def main(cand_path: str, out_path: str) -> int:
    cands = json.loads(Path(cand_path).read_text())
    out = {}
    for c in cands:
        k = f"{c['key']}::{c['repo_path']}"
        try:
            r = probe_file(c["local_path"])
        except Exception as e:  # noqa: BLE001
            r = {"status": "probe_error", "exc": str(e)[:200]}
        r["family"] = c.get("family", "")
        out[k] = r
        n = r.get("n_bottom", "?")
        print(f"[{k}] status={r['status']} n_bottom={n} "
              f"any_sibling_rows={any(b.get('sibling_rows_in_scope') for b in r.get('bottoms', []))}",
              file=sys.stderr, flush=True)
    Path(out_path).write_text(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
