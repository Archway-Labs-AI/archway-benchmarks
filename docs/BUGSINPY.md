# BugsInPy benchmark — machinery overview

BugsInPy is hosted here **in the same pattern as TypeEvalPy**: a vendored corpus
submodule, a loader, a scorer, a run store, and a progress report. It is
**machinery only** — no scoring run, no numbers, no bug classification, and no
Archway+agent experiment live in this layer.

## What BugsInPy is
~501 real Python bugs across ~17 real projects. Each bug ships a buggy version,
a fixed version, the patch, and **failing tests** that pass on the fixed
version. Two standard scoring modes, both first-class in the machinery:

- **Detection** (Track 1, deterministic analysis): did a tool flag the bug's
  location? Scored against the patch's touched lines.
- **Repair** (Track 2, the later agent experiment): did a candidate fix make the
  failing tests pass? Scored by the test-suite-passes metric.

Both modes are supported even though **neither is run here**.

## Vendoring (done — pinned submodule on our fork)
Vendored as a submodule on the `Archway-Labs-AI` fork, exactly like TypeEvalPy.
`.gitmodules` declares it and the gitlink is committed:

```
[submodule "extras/BugsInPy"]
	path = extras/BugsInPy
	url = git@github.com:Archway-Labs-AI/BugsInPy.git
```

Populate it on a fresh checkout with `git submodule update --init extras/BugsInPy`.

**Upstream choice.** We deliberately did **not** fork the stale original
`soarsmu/BugsInPy` (an independent study reproduced only ~67% of its bugs, and
it tracks no active/deprecated status). `Archway-Labs-AI/BugsInPy` is forked from
the UIUC **`reproducing-research-projects/BugsInPy`** — the "Reproducing and
Improving BugsInPy" reproduction, which keeps the identical
`projects/<p>/bugs/<id>/{bug.info,bug_patch.txt,run_test.sh}` layout the loader
expects (plus extras like `bug_buggy.txt`/`bug_fixed.txt`/`bugsinpy-index.csv`,
which the loader ignores) while fixing reproducibility. The Cerberus
`nus-apr/bugs-in-py-benchmark` was rejected: it restructures the corpus around
its own framework (root-level projects + build scaffolding), a poor fit for our
loader. Pinned at `316b95e` (501 bugs / 17 projects; 500 carry patch-derived
locations).

The unit tests do **not** need the corpus — they run against
`tests/fixtures/bugsinpy/` (a 3-bug, 2-project fixture mirroring the real
on-disk layout).

## Layout (parallel to TypeEvalPy)
| Concern | TypeEvalPy | BugsInPy |
| --- | --- | --- |
| Types | `types.py` | `bugsinpy_types.py` |
| Loader | `benchmarks/typeevalpy.py` | `benchmarks/bugsinpy.py` |
| Scorer | `scoring/typeevalpy.py` | `scoring/bugsinpy.py` (both modes) |
| Engine seam | `engines/archway.py` | `engines/bugsinpy.py` (repair runner) |
| Store | `store.py` (annotations/scores) | `store.py` (`bugsinpy_*` tables) |
| Report | `reports.py` + `_progress_markdown` | `bugsinpy_report.py` |
| Manifest | `manifest.py` | `bugsinpy_manifest.py` |
| CLI | `cli.py` | `bugsinpy_cli.py` (registered into `cli.py`) |

## The loader exposes (per bug, for a LATER classification pass)
`project`, `bug_id`, `buggy_commit`, `fixed_commit`, the patch, the failing
tests, `files_touched`, `n_files_touched`, `lines_changed`, and the
patch-derived `bug_locations` (the detection ground truth). It makes **no
tractability judgment** — `archway-bench bugsinpy-manifest` dumps this metadata
so Ben's separate manual-validation pass can subset by bug shape.

## Provenance + subsets (the honesty discipline)
Every run records, in `runs.metadata`: `mode`, `engine_sha`, `corpus_commit`,
and the declared `subset`. So a result is never a cold number — it is bound to
the engine + corpus it was produced against, and you can report **subset AND
full** rather than one figure.

## How a FUTURE run is invoked (nothing runs here)
```bash
# Detection on a declared subset:
archway-bench bugsinpy-detect --flagged flags.json \
    --subset-project black pandas \
    --engine-sha <engine-sha> --corpus-commit <corpus-commit>

# Repair on a declared subset, via the BugsInPy framework runner:
archway-bench bugsinpy-repair --fixes fixes.json --runner framework \
    --subset-key black:1 black:3 \
    --engine-sha <engine-sha> --corpus-commit <corpus-commit>

# Render the progress report:
archway-bench bugsinpy-progress --out-md bugsinpy_progress.md

# Dump per-bug metadata (for the later classification pass):
archway-bench bugsinpy-manifest -o bugsinpy_manifest.json
```

- `flags.json`: `{"black:1": [{"file": "src/black.py", "lines": [120, 121]}], ...}`
  — a detector's flagged locations per bug.
- `fixes.json`: `{"black:1": "<unified diff to apply to the buggy checkout>", ...}`
  — an agent's candidate fix per bug. `--runner stub` scores without the
  framework (tests); `--runner framework` shells out to `bugsinpy-checkout` +
  `bugsinpy-run_test`.

## Directional bucketer (DIAGNOSTIC — not claim-grade)
`bugsinpy_bucketer.py` derives a coarse bug **class** from what the fix PATCH
does — `none_or_null` · `type_check` · `missing_branch` · `exception_handling` ·
`api_misuse_lib` · `other` — to *direct* attention, not to make a claim. Every
output is labelled **DIRECTIONAL/DIAGNOSTIC pending Ben's validation**.

- **Patch-evidenced**: e.g. a fix that adds `is None` → `none_or_null`; adds
  `except` → `exception_handling`; adds `isinstance(` → `type_check`. A merely
  *changed* return value is **not** a missing branch (→ `other`).
- **Confidence**: `high` where the patch confirms the class, `low` where guessed.
  `api_misuse_lib` is always `low` (not cheaply confirmable).
- **Re-computable + versioned**: buckets are stored keyed by
  `(bug_key, BUCKETER_VERSION)` — a property of the bug, **not** of a run. Bumping
  the version (or editing rules) and re-running re-buckets the SAME stored
  detection results **without re-running the benchmark**.
- **Reportable by bucket**: `bugsinpy-bucket-report` joins a detection run ×
  a bucketer version → detection rate × class, with version + confidence visible.
- **Needs-adjudication queue**: the `low`-confidence + `api_misuse_lib` bugs are
  surfaced as the human-review list (`bugsinpy-adjudicate`).

```bash
archway-bench bugsinpy-bucket --version v1          # compute + store buckets (DIRECTIONAL)
archway-bench bugsinpy-adjudicate --version v1      # the needs-adjudication queue
archway-bench bugsinpy-bucket-report --run <N> --version v1   # detection rate × class
```

It classifies **nothing definitively**. Tractability decisions remain Ben's
separate manual pass.

## Explicitly out of scope (not in this layer)
Running the benchmark / producing any number; classifying bugs definitively into
tractable classes (Ben's manual pass — the bucketer is directional input to it,
not a substitute); the IR-vs-no-IR repair experiment; committing any result.
