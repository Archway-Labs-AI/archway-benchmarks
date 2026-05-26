"""Sync the canonical TypeEvalPy mapping module into the upstream artifact.

Source of truth: `src/archway_benchmarks/typeevalpy_mapping.py`
Mirror:         `upstream/target_tools/archway/src/typeevalpy_mapping.py`

Run this after editing the source. The companion test
`tests/test_upstream_sync.py` asserts the two files are byte-identical so a
drift surfaces in CI rather than silently scoring against two slightly
different schemas.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "archway_benchmarks" / "typeevalpy_mapping.py"
DEST = ROOT / "upstream" / "target_tools" / "archway" / "src" / "typeevalpy_mapping.py"


def main() -> int:
    if not SRC.exists():
        print(f"missing source: {SRC}", file=sys.stderr)
        return 1
    DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SRC, DEST)
    print(f"copied {SRC.relative_to(ROOT)} -> {DEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
