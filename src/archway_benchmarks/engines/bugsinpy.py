"""BugsInPy engine seam — the repair runner (parallel to `engines/archway.py`).

Detection mode needs no engine here: a tool emits flagged locations and
`scoring.bugsinpy.score_detection` joins them against GT. Repair mode needs an
engine that, given a candidate fix, RUNS the bug's failing tests — this is that
seam. Keeping it behind a Protocol means the scorer stays pure and testable (a
`StubTestRunner` drives the unit tests) while the real runner shells out to the
BugsInPy framework. Nothing is executed by this task.

The real runner mirrors the BugsInPy CLI workflow:
  bugsinpy-checkout -p <project> -v 0 -i <id> -w <work>   # buggy version
  <apply candidate fix patch to the checkout>
  bugsinpy-run_test                                        # the failing tests
A test suite that now passes is the repair plausibility signal.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from archway_benchmarks.bugsinpy_types import BugRecord, TestOutcome


@dataclass(frozen=True)
class CandidateFix:
    """A proposed repair: a unified diff to apply to the BUGGY checkout.

    For the later IR-vs-no-IR agent experiment, the agent produces this; the
    runner applies it and runs the failing tests. `patch=""` means 'no fix'
    (used to confirm the tests fail on the unmodified buggy version).
    """

    bug_key: str
    patch: str


class BugTestRunner(Protocol):
    """The repair engine seam. One method: run a bug's failing tests against a
    candidate fix and report the test-suite-passes outcome."""

    name: str

    def run_failing_tests(self, bug: BugRecord, fix: CandidateFix) -> TestOutcome: ...


class BugsInPyTestRunner:
    """Real runner: drives the vendored BugsInPy framework. Wired, not invoked
    here (this task runs nothing). Requires the BugsInPy CLI on PATH and the
    corpus submodule initialized.
    """

    name = "bugsinpy-framework"

    def __init__(self, corpus_root: Path, *, framework_bin: Path | None = None,
                 work_dir: Path | None = None, timeout_s: int = 1800) -> None:
        self.corpus_root = Path(corpus_root)
        self.framework_bin = framework_bin or (self.corpus_root / "framework" / "bin")
        self.work_dir = work_dir or Path("/tmp/bugsinpy_work")
        self.timeout_s = timeout_s

    def run_failing_tests(self, bug: BugRecord, fix: CandidateFix) -> TestOutcome:
        """Checkout buggy → apply fix → run failing tests → parse pass/fail.

        Deliberately conservative: any framework/setup failure yields a
        non-passing outcome with the reason in `detail`, never a false PASS.
        """
        checkout = self.work_dir / bug.project
        try:
            self._checkout(bug, checkout)
            if fix.patch.strip():
                self._apply_patch(checkout, fix.patch)
            return self._run_tests(bug, checkout)
        except (OSError, subprocess.SubprocessError) as e:  # never a false pass
            return TestOutcome(bug_key=bug.key, project=bug.project, passed=False,
                               n_tests=len(bug.failing_tests), n_passed=0,
                               n_failed=len(bug.failing_tests), detail=f"runner error: {e}")

    # ----- framework calls (shell-outs; not exercised by this task) -----

    def _checkout(self, bug: BugRecord, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [str(self.framework_bin / "bugsinpy-checkout"), "-p", bug.project,
             "-v", "0", "-i", bug.bug_id, "-w", str(dest)],
            check=True, capture_output=True, text=True, timeout=self.timeout_s,
        )

    def _apply_patch(self, checkout: Path, patch: str) -> None:
        proc = subprocess.run(["git", "-C", str(checkout), "apply", "-"],
                              input=patch, capture_output=True, text=True)
        if proc.returncode != 0:
            raise subprocess.SubprocessError(f"git apply failed: {proc.stderr[:400]}")

    def _run_tests(self, bug: BugRecord, checkout: Path) -> TestOutcome:
        proc = subprocess.run(
            [str(self.framework_bin / "bugsinpy-run_test"), "-w", str(checkout)],
            capture_output=True, text=True, timeout=self.timeout_s,
        )
        passed = proc.returncode == 0
        n = len(bug.failing_tests)
        return TestOutcome(bug_key=bug.key, project=bug.project, passed=passed,
                           n_tests=n, n_passed=n if passed else 0,
                           n_failed=0 if passed else n, detail=proc.stdout[-400:])


class StubTestRunner:
    """Deterministic stub for unit tests — repairs exactly the bug keys it was
    told to. Lets the scorer be exercised end-to-end without the framework."""

    name = "stub"

    def __init__(self, repaired_keys: set[str]) -> None:
        self.repaired_keys = repaired_keys

    def run_failing_tests(self, bug: BugRecord, fix: CandidateFix) -> TestOutcome:
        ok = bug.key in self.repaired_keys
        n = len(bug.failing_tests) or 1
        return TestOutcome(bug_key=bug.key, project=bug.project, passed=ok,
                           n_tests=n, n_passed=n if ok else 0,
                           n_failed=0 if ok else n, detail="stub")
