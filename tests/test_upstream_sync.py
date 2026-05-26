"""Enforce that the upstream Archway tool's mapping module is byte-identical
to the harness canonical source. Drift here would mean the upstream tool
emits records under a slightly different schema than the harness scores
itself on — a silent correctness bug across the leaderboard.

Run `python scripts/sync_upstream_mapping.py` after editing the canonical
source.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "archway_benchmarks" / "typeevalpy_mapping.py"
MIRROR = ROOT / "upstream" / "target_tools" / "archway" / "src" / "typeevalpy_mapping.py"


def test_mapping_module_is_byte_identical():
    assert SRC.exists(), f"canonical missing: {SRC}"
    assert MIRROR.exists(), (
        f"upstream mirror missing: {MIRROR}. Run scripts/sync_upstream_mapping.py."
    )
    assert SRC.read_bytes() == MIRROR.read_bytes(), (
        "upstream Archway tool's typeevalpy_mapping.py has drifted from the "
        "canonical source. Run `python scripts/sync_upstream_mapping.py` and "
        "commit both files."
    )
