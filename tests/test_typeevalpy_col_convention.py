"""Pin the TypeEvalPy `col_offset` convention against the vendored GT.

If TypeEvalPy ever changes how it indexes columns (or if we accidentally
break our 1-indexed assumption), this test fails before the engine plug-in
silently produces LOCATION_MISS on every annotation.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "extras" / "TypeEvalPy" / "micro-benchmark" / "python_features"


def _find(records, **fields):
    for r in records:
        if all(r.get(k) == v for k, v in fields.items()):
            return r
    raise KeyError(f"no GT record matching {fields}")


def test_col_offset_is_1_indexed_for_variable_name():
    """`a, b = func1, func2` on line 14 of assignments/tuple/main.py.
    GT col_offset=1 -> 'a'. Python ast would say 0. Confirms 1-indexed."""
    snip = CORPUS / "assignments" / "tuple"
    gt = json.loads((snip / "main_gt.json").read_text())
    src_line = (snip / "main.py").read_text().splitlines()[14 - 1]
    rec_a = _find(gt, line_number=14, variable="a")
    rec_b = _find(gt, line_number=14, variable="b")
    assert src_line == "a, b = func1, func2"
    # `a` is the first character of the line.
    assert rec_a["col_offset"] == 1, rec_a
    # `b` is at character index 3 in the line (0-indexed) -> 4 in 1-indexed.
    assert rec_b["col_offset"] == 4, rec_b


def test_col_offset_is_1_indexed_for_function_def():
    """`def my_sum(a, b, *integers):` on line 4 of args/multiple/main.py.
    GT col_offset=5 -> first char of 'my_sum' is 1-indexed col 5."""
    snip = CORPUS / "args" / "multiple"
    gt = json.loads((snip / "main_gt.json").read_text())
    src_line = (snip / "main.py").read_text().splitlines()[4 - 1]
    rec_return = _find(gt, line_number=4, function="my_sum", col_offset=5)
    rec_param_a = _find(gt, line_number=4, function="my_sum", parameter="a")
    assert src_line.startswith("def my_sum(")
    # `m` of `my_sum` is at 0-indexed col 4 -> 1-indexed col 5.
    assert rec_return["col_offset"] == 5
    # `a` of `def my_sum(a, ...` is at 0-indexed col 11 -> 1-indexed col 12.
    assert rec_param_a["col_offset"] == 12
