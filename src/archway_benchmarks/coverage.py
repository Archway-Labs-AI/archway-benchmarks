"""Per-snippet translation coverage status.

Drives the dashboard's all-vs-covered dual reporting: a snippet's contribution
to the leaderboard-comparable "all 850" number is independent of whether our
translation engine can currently handle it, but the "covered subset" number
filters to those we attempted. With the stub everything is COVERED.
"""
from __future__ import annotations

from enum import Enum


class CoverageStatus(str, Enum):
    COVERED = "COVERED"  # translation succeeded fully
    PARTIAL = "PARTIAL"  # translation succeeded but with gaps the engine reported
    UNSUPPORTED = "UNSUPPORTED"  # translation failed; we did not attempt the snippet


class UnsupportedSourceError(Exception):
    """Raised by a TranslationEngine when it cannot translate a source.

    The Runner converts this into `CoverageStatus.UNSUPPORTED` and skips
    analysis for that snippet, persisting it in the run store so the
    dashboard can show "what we did not even attempt".
    """
