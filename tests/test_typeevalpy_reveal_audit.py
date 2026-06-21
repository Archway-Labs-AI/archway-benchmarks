from __future__ import annotations

import json
from pathlib import Path

from archway_benchmarks.typeevalpy_reveal_audit import (
    classify_audit,
    classify_unsupported_gt,
    parse_pyrefly_reveal_observations,
    reconcile_imported_class_types,
)


def test_classifies_lambda_parameter_gt_as_unsupported() -> None:
    source = "y = lambda x: x + 1\n"
    gt = [
        {
            "file": "main.py",
            "line_number": 1,
            "col_offset": 11,
            "function": "lambda",
            "parameter": "x",
            "type": ["int"],
        }
    ]

    assert classify_unsupported_gt(gt, source) == {0: "unsupported_lambda_parameter_probe"}


def test_preserves_unknown_any_never_as_audit_observation() -> None:
    payload = {
        "errors": [
            {"name": "reveal-type", "line": 3, "description": "revealed type: Unknown | Any"}
        ]
    }
    gt = [{"parameter": "x", "function": "f", "type": ["int"]}]

    observations = parse_pyrefly_reveal_observations(
        payload=payload,
        line_to_gt={3: 0},
        flatten=lambda _: [],
        gt=gt,
        source="def f(x):\n    pass\n",
    )
    classified = classify_audit(
        gt,
        [{"gt_index": 0, "entry": gt[0], "status": "planned"}],
        observations,
    )

    assert observations[0].raw_type == "Unknown | Any"
    assert observations[0].dropped_reason == "unknown_any_never"
    assert classified[0].status == "unknown_any_never_preserved"


def test_reconciles_imported_class_only_with_assignment_evidence() -> None:
    source = "import to_import\n\na = to_import.A()\n"
    entry = {"line_number": 3, "variable": "a", "type": ["to_import.A"]}

    assert reconcile_imported_class_types(
        normalized_types=["A"], entry=entry, source=source
    ) == ["to_import.A"]


def test_does_not_guess_import_qualification_without_evidence() -> None:
    source = "class A:\n    pass\n\na = A()\n"
    entry = {"line_number": 4, "variable": "a", "type": ["A"]}

    assert reconcile_imported_class_types(normalized_types=["A"], entry=entry, source=source) == ["A"]
