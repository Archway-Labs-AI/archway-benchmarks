"""BugsInPy benchmark — parallel to `benchmarks/typeevalpy.py`.

Loads bugs from the vendored BugsInPy corpus
(`extras/BugsInPy/projects/<project>/bugs/<id>/`), parsing each bug's
`bug.info` (commits + failing tests), `bug_patch.txt` (the fix diff, from which
we derive the detection ground-truth location), and the project's
`project.info` (github url). Exposes per-bug metadata so downstream work can
subset by bug shape WITHOUT this module classifying anything.

Mirrors TypeEvalPy's loader structure: a corpus root resolved at import time, a
cached `load()`, a `ground_truth_*` projection, and a `subset()` selector. The
scorer is wired in `archway_benchmarks.scoring.bugsinpy` (both modes).

On-disk format (BugsInPy upstream, soarsmu/BugsInPy):
  projects/<project>/project.info          github_url="...", status="..."
  projects/<project>/bugs/<id>/bug.info    python_version, buggy_commit_id,
                                           fixed_commit_id, test_file, test_list
  projects/<project>/bugs/<id>/bug_patch.txt   unified diff (buggy -> fixed)
  projects/<project>/bugs/<id>/run_test.sh     the concrete test command(s)
"""
from __future__ import annotations

import re
from pathlib import Path

from archway_benchmarks.bugsinpy_types import BugLocation, BugRecord

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CORPUS = _REPO_ROOT / "extras" / "BugsInPy"

# `key="value"` / `key=value` shell-style assignment used by bug.info & project.info.
_KV_RE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*"?(.*?)"?\s*$')
# Unified-diff file header (prefer the `+++ b/<path>` / `--- a/<path>` lines).
_DIFF_FILE_RE = re.compile(r'^\+\+\+ [ab]/(.+?)\s*$')
_DIFF_OLDFILE_RE = re.compile(r'^--- [ab]/(.+?)\s*$')
_HUNK_RE = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


class BugsInPyBenchmark:
    """The BugsInPy corpus. Parallel to `TypeEvalPyBenchmark`."""

    name = "bugsinpy"

    def __init__(self, corpus_root: Path | None = None) -> None:
        self.corpus_root = Path(corpus_root) if corpus_root else _DEFAULT_CORPUS
        if not self.corpus_root.exists():
            raise FileNotFoundError(
                f"BugsInPy corpus not found at {self.corpus_root}. "
                "Initialize the submodule: `git submodule update --init --recursive`."
            )
        self._bugs: list[BugRecord] | None = None

    # ----- Benchmark API (parallel to TypeEvalPyBenchmark) -----

    def load(self) -> list[BugRecord]:
        if self._bugs is not None:
            return self._bugs

        bugs: list[BugRecord] = []
        projects_root = self.corpus_root / "projects"
        if not projects_root.exists():
            # tolerate a corpus that puts projects at the root
            projects_root = self.corpus_root
        for project_dir in sorted(p for p in projects_root.iterdir() if p.is_dir()):
            github_url = self._parse_project_info(project_dir).get("github_url")
            bugs_dir = project_dir / "bugs"
            if not bugs_dir.exists():
                continue
            for bug_dir in sorted(bugs_dir.iterdir(), key=_numeric_key):
                if not bug_dir.is_dir():
                    continue
                rec = self._load_bug(project_dir.name, bug_dir, github_url)
                if rec is not None:
                    bugs.append(rec)

        self._bugs = bugs
        return bugs

    def ground_truth_detection(self) -> dict[str, tuple[BugLocation, ...]]:
        """`bug_key -> patch-derived buggy regions`. The detection oracle's GT."""
        return {b.key: b.bug_locations for b in self.load()}

    def subset(self, *, projects: list[str] | None = None,
               bug_keys: list[str] | None = None) -> list[BugRecord]:
        """Declared subset selector — the only filtering this task supports.

        Filters by project and/or explicit `project:bug_id` keys. Records WHICH
        bugs are in the subset so a run can report 'subset AND full'. This does
        NOT classify by tractability — that is Ben's separate manual pass.
        """
        bugs = self.load()
        if projects is not None:
            allow = set(projects)
            bugs = [b for b in bugs if b.project in allow]
        if bug_keys is not None:
            allow_k = set(bug_keys)
            bugs = [b for b in bugs if b.key in allow_k]
        return bugs

    def corpus_commit(self) -> str | None:
        """The vendored corpus's pinned commit — provenance for any future run."""
        import subprocess
        try:
            out = subprocess.run(
                ["git", "-C", str(self.corpus_root), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=False,
            )
            return out.stdout.strip() or None
        except OSError:
            return None

    # ----- internals -----

    def _load_bug(self, project: str, bug_dir: Path, github_url: str | None) -> BugRecord | None:
        info_path = bug_dir / "bug.info"
        if not info_path.exists():
            return None
        info = _parse_kv(info_path.read_text())
        patch_path = bug_dir / "bug_patch.txt"
        patch = patch_path.read_text() if patch_path.exists() else ""
        locations = _parse_patch(patch)

        files_touched = tuple(sorted({loc.file for loc in locations}))
        lines_changed = sum(len(loc.lines) for loc in locations)
        failing_tests = _parse_tests(info, bug_dir)
        test_files = tuple(t for t in _split_list(info.get("test_file", "")) if t)

        return BugRecord(
            project=project,
            bug_id=bug_dir.name,
            buggy_commit=info.get("buggy_commit_id", ""),
            fixed_commit=info.get("fixed_commit_id", ""),
            bug_locations=locations,
            failing_tests=failing_tests,
            test_files=test_files,
            patch=patch,
            python_version=info.get("python_version") or None,
            github_url=github_url,
            files_touched=files_touched,
            n_files_touched=len(files_touched),
            lines_changed=lines_changed,
        )

    def _parse_project_info(self, project_dir: Path) -> dict[str, str]:
        p = project_dir / "project.info"
        return _parse_kv(p.read_text()) if p.exists() else {}


# ----- parsing helpers -----

def _numeric_key(path: Path):
    """Sort bug dirs numerically (1,2,...,10) when ids are integers."""
    name = path.name
    return (0, int(name)) if name.isdigit() else (1, name)


def _parse_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _KV_RE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _split_list(value: str) -> list[str]:
    """BugsInPy lists tests separated by `;`, `\n`, or whitespace."""
    if not value:
        return []
    parts = re.split(r'[;\n]+', value)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if p:
            out.append(p)
    return out


def _parse_tests(info: dict[str, str], bug_dir: Path) -> tuple[str, ...]:
    """Failing test ids: prefer bug.info `test_list`, else fall back to the test
    commands in run_test.sh (so the repair runner has something to execute)."""
    tests = _split_list(info.get("test_list", ""))
    if tests:
        return tuple(tests)
    rt = bug_dir / "run_test.sh"
    if rt.exists():
        return tuple(l.strip() for l in rt.read_text().splitlines()
                     if l.strip() and not l.lstrip().startswith("#"))
    return ()


def _parse_patch(patch: str) -> tuple[BugLocation, ...]:
    """Extract buggy-side touched regions from a unified diff.

    BugsInPy's `bug_patch.txt` is a `buggy -> fixed` diff, so the old-side
    (`-`) lines are the BUGGY locations. For each hunk we walk the old-side
    line counter and record every removed line.

    A pure-insertion fix (a hunk that removes nothing — e.g. adding a missing
    guard or branch) has no removed line to anchor on. There the bug lives *at
    the gap* the inserted code fills, so we record the buggy-side context lines
    immediately bracketing each insertion point (the line before and after),
    not a single hunk-start anchor — a tighter, more faithful detection region.
    A hunk with neither removed nor bracketing lines falls back to its old-side
    start. Direction-robust at file granularity regardless of patch convention.
    """
    locations: list[BugLocation] = []
    current_file: str | None = None
    old_line = 0
    hunk_lines: set[int] = set()      # buggy lines the patch removed
    ins_brackets: set[int] = set()    # buggy lines bracketing pure insertions
    hunk_old_start = 0

    def flush(file: str | None, removed: set[int], brackets: set[int], anchor: int) -> None:
        if file is None:
            return
        # Removed lines are the truest signal; for a pure insertion fall back to
        # the lines bracketing the insertion; failing both, the hunk's anchor.
        lines = removed or brackets or ({anchor} if anchor else set())
        if lines:
            locations.append(BugLocation(file=file, start=min(lines), end=max(lines),
                                         lines=frozenset(lines)))

    for line in patch.splitlines():
        fm = _DIFF_FILE_RE.match(line)
        if fm:
            flush(current_file, hunk_lines, ins_brackets, hunk_old_start)
            hunk_lines = set()
            ins_brackets = set()
            hunk_old_start = 0  # don't let this file's anchor leak into the next
            current_file = fm.group(1)
            continue
        if line.startswith('--- '):
            om = _DIFF_OLDFILE_RE.match(line)
            if om and current_file is None:
                current_file = om.group(1)
            continue
        hm = _HUNK_RE.match(line)
        if hm:
            flush(current_file, hunk_lines, ins_brackets, hunk_old_start)
            hunk_lines = set()
            ins_brackets = set()
            old_line = int(hm.group(1))
            hunk_old_start = old_line
            continue
        if current_file is None:
            continue
        if line.startswith('-') and not line.startswith('---'):
            hunk_lines.add(old_line)
            old_line += 1
        elif line.startswith('+') and not line.startswith('+++'):
            # Fixed-side only; doesn't advance the buggy counter. Record the
            # buggy lines bracketing this insertion point (used only if the hunk
            # removes nothing): the existing line after it, and the one before.
            ins_brackets.add(old_line)
            if old_line - 1 >= 1:
                ins_brackets.add(old_line - 1)
        elif line.startswith(' ') or line == '':
            old_line += 1

    flush(current_file, hunk_lines, ins_brackets, hunk_old_start)
    # merge per-file
    by_file: dict[str, set[int]] = {}
    for loc in locations:
        by_file.setdefault(loc.file, set()).update(loc.lines)
    return tuple(
        BugLocation(file=f, start=min(ls), end=max(ls), lines=frozenset(ls))
        for f, ls in sorted(by_file.items()) if ls
    )
