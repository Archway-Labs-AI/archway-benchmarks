"""Per-annotation outcome bucket.

Whether a failure was the functor (wrong type at the right place) vs. the
translation/coordinate plumbing (right type at the wrong place — or no
emission at all) is the key signal for development triage. The harness must
never collapse these into a single "wrong" bucket.
"""
from __future__ import annotations

from enum import Enum


class Outcome(str, Enum):
    EXACT = "EXACT"  # location matched and normalized type set matched
    TYPE_MISS = "TYPE_MISS"  # location matched, normalized type set differed
    LOCATION_MISS = "LOCATION_MISS"  # no prediction at the GT location key
    SPURIOUS = "SPURIOUS"  # a prediction at no GT location (hurts soundness)
