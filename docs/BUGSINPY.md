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

## Vendoring (the one remaining step — needs the GitHub fork)
TypeEvalPy is vendored as a submodule on the `Archway-Labs-AI` fork. BugsInPy
mirrors that. `.gitmodules` already declares it:

```
[submodule "extras/BugsInPy"]
	path = extras/BugsInPy
	url = git@github.com:Archway-Labs-AI/BugsInPy.git
```

To populate it (Ben, once the fork exists):

```bash
# 1. fork soarsmu/BugsInPy -> Archway-Labs-AI/BugsInPy
# 2. register + pin the submodule at the path .gitmodules already declares
git submodule add git@github.com:Archway-Labs-AI/BugsInPy.git extras/BugsInPy
git -C extras/BugsInPy checkout <pinned-commit>
git add .gitmodules extras/BugsInPy
```

Until then the loader raises a clear `FileNotFoundError` pointing at
`git submodule update --init`. The unit tests do **not** need the corpus — they
run against `tests/fixtures/bugsinpy/` (a 3-bug, 2-project fixture mirroring the
real on-disk layout).

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

## Explicitly out of scope (not in this layer)
Running the benchmark / producing any number; classifying bugs into tractable
classes (Ben's manual pass); the IR-vs-no-IR repair experiment; committing any
result.
