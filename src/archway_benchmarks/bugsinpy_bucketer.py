"""DIRECTIONAL / DIAGNOSTIC bug bucketer — patch-evidenced, versioned, re-computable.

**Not claim-grade.** This derives a coarse bug CLASS from what the fix PATCH does,
cheaply, to *direct* attention (which classes detection catches; which bugs need
a human look). It classifies NOTHING definitively, runs nothing, publishes
nothing — every output is labelled DIRECTIONAL pending manual validation.

Design points the machinery guarantees:
  - Buckets are a property of the BUG (its patch), not of a benchmark run, so
    they are **re-computable**: bucketing is keyed by `(bug_key, bucketer_version)`
    in the store. Bumping `BUCKETER_VERSION` (or editing the rules) and re-running
    the bucketer re-buckets the SAME stored detection RESULTS — no benchmark re-run.
  - Each bug gets a CONFIDENCE: `high` where the patch confirms the class
    (e.g. an `except` or an `is None` guard was literally added), `low` where it
    is a guess. `api_misuse_lib` is always `low` — it cannot be confirmed cheaply.
  - The low-confidence + `api_misuse_lib` bugs are the **needs-adjudication** list.

Classes: none_or_null · type_check · missing_branch · exception_handling ·
         api_misuse_lib · other
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark
    from archway_benchmarks.bugsinpy_types import BugRecord

# Bump to re-bucket stored results without re-running the benchmark.
BUCKETER_VERSION = "v1"

BUCKET_CLASSES = (
    "none_or_null",
    "type_check",
    "missing_branch",
    "exception_handling",
    "api_misuse_lib",
    "other",
)

DIRECTIONAL_NOTE = ("DIRECTIONAL/DIAGNOSTIC — patch-evidenced heuristic, NOT claim-grade; "
                    "pending manual validation.")


@dataclass(frozen=True)
class BucketResult:
    bug_key: str
    project: str
    bucket: str
    confidence: str  # "high" | "low"
    bucketer_version: str
    evidence: str  # the matched pattern + a sample line — shown so a human can check

    @property
    def needs_adjudication(self) -> bool:
        return self.confidence == "low" or self.bucket == "api_misuse_lib"


# ----- patch evidence extraction -----

def _added_lines(patch: str) -> list[str]:
    return [l[1:] for l in patch.splitlines()
            if l.startswith("+") and not l.startswith("+++")]


def _removed_lines(patch: str) -> list[str]:
    return [l[1:] for l in patch.splitlines()
            if l.startswith("-") and not l.startswith("---")]


# Patterns matched against the FIX's added (and sometimes removed) lines. The fix
# reveals the bug: a fix that adds an `is None` guard means a missing None check.
_RE_NONE = re.compile(r"\bis\s+not\s+None\b|\bis\s+None\b|[!=]=\s*None\b|\bor\s+None\b|\bif\s+not\s+\w")
_RE_NONE_WEAK = re.compile(r"\bNone\b")
_RE_EXC = re.compile(r"^\s*(try|except|finally)\b|(^|\W)raise\s+\w")
_RE_TYPE_STRONG = re.compile(r"\bisinstance\s*\(|\bissubclass\s*\(")
_RE_TYPE_WEAK = re.compile(r"\btype\s*\(|\.astype\s*\(|\bcast\s*\(|:\s*[A-Z]\w+\b")
_RE_COND = re.compile(r"^\s*(if|elif|else)\b")            # a real conditional added
_RE_GUARD = re.compile(r"^\s*(return|continue|break)\b")  # a guard added (only if not just changed)
# A call whose receiver looks like an imported library symbol, or a kwarg/arg change.
_RE_API = re.compile(r"\b[a-z_][\w.]*\.[a-z_]\w*\s*\(|=\s*[a-z_][\w.]*\s*\(")


def bucket_bug(bug: "BugRecord", *, version: str = BUCKETER_VERSION) -> BucketResult:
    """Classify one bug from its patch. Cheap, ordered, evidence-tagged."""
    added = _added_lines(bug.patch)
    removed = _removed_lines(bug.patch)
    added_text = "\n".join(added)
    changed_text = "\n".join(added + removed)

    def mk(bucket: str, confidence: str, pat: str, sample_pool: list[str]) -> BucketResult:
        sample = next((l.strip() for l in sample_pool if re.search(pat, l)), "")[:120]
        return BucketResult(bug_key=bug.key, project=bug.project, bucket=bucket,
                            confidence=confidence, bucketer_version=version,
                            evidence=f"{pat!r} :: {sample}" if sample else pat)

    # Precedence: most specific / most confirmable first.
    if _RE_EXC.search(added_text):
        return mk("exception_handling", "high", _RE_EXC.pattern, added)
    if _RE_NONE.search(added_text):
        return mk("none_or_null", "high", _RE_NONE.pattern, added)
    if _RE_TYPE_STRONG.search(changed_text):
        return mk("type_check", "high", _RE_TYPE_STRONG.pattern, added + removed)
    if _RE_NONE_WEAK.search(added_text):
        return mk("none_or_null", "low", _RE_NONE_WEAK.pattern, added)
    if _RE_TYPE_WEAK.search(changed_text):
        return mk("type_check", "low", _RE_TYPE_WEAK.pattern, added + removed)
    # missing_branch: a real conditional added (high), or a guard inserted — NOT a
    # merely *changed* return/continue (which is an expression fix, not a new branch).
    if any(_RE_COND.match(l) for l in added):
        return mk("missing_branch", "high", _RE_COND.pattern, added)
    if any(_RE_GUARD.match(l) for l in added) and not any(_RE_GUARD.match(l) for l in removed):
        return mk("missing_branch", "low", _RE_GUARD.pattern, added)
    if _RE_API.search(changed_text):
        return mk("api_misuse_lib", "low", _RE_API.pattern, added + removed)  # never confirmable cheap
    return BucketResult(bug_key=bug.key, project=bug.project, bucket="other",
                        confidence="low", bucketer_version=version, evidence="no rule matched")


def bucket_all(benchmark: "BugsInPyBenchmark", *, version: str = BUCKETER_VERSION,
               subset: set[str] | None = None) -> list[BucketResult]:
    bugs = benchmark.load()
    if subset is not None:
        bugs = [b for b in bugs if b.key in subset]
    return [bucket_bug(b, version=version) for b in bugs]


def needs_adjudication(results: list[BucketResult]) -> list[BucketResult]:
    """The low-confidence + api_misuse_lib bugs — the human-review queue."""
    return [r for r in results if r.needs_adjudication]


def summarize(results: list[BucketResult]) -> dict:
    by_bucket: dict[str, dict[str, int]] = {c: {"high": 0, "low": 0} for c in BUCKET_CLASSES}
    for r in results:
        by_bucket.setdefault(r.bucket, {"high": 0, "low": 0})[r.confidence] += 1
    return {
        "bucketer_version": results[0].bucketer_version if results else BUCKETER_VERSION,
        "total": len(results),
        "by_bucket": by_bucket,
        "needs_adjudication": len(needs_adjudication(results)),
        "note": DIRECTIONAL_NOTE,
    }
