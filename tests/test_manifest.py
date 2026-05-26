"""Sanity-check the manifest against the reachability numbers in the spec.

Spec: minimal_floor ≈ 399 / 46%, +classes ≈ 550 / 64%, no-imports ≈ 732 / 86%,
function parameters = 95, callable GT = 150, total = 850 across 153 snippets.
"""
from archway_benchmarks.manifest import generate


def test_manifest_matches_spec_reachability():
    m = generate()
    s = m.summary()

    assert s["total_snippets"] == 153
    assert s["total_annotations"] == 850
    assert s["minimal_floor_annotations"] == 399
    assert s["classes_slice_annotations"] == 550
    assert s["function_parameter_annotations"] == 95
    assert s["callable_gt_annotations"] == 150
    # 86% target from spec: allow ±3% wiggle since import detection is heuristic
    assert 82.0 <= s["no_imports_slice_pct"] <= 89.0


def test_manifest_payoff_curve_is_monotonic():
    m = generate()
    s = m.summary()
    assert (
        s["minimal_floor_annotations"]
        <= s["classes_slice_annotations"]
        <= s["no_imports_slice_annotations"]
        <= s["total_annotations"]
    )
