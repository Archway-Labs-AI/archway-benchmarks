# Upstream contribution staging

Two artifacts here are designed to drop cleanly into a fork of
`secure-software-engineering/TypeEvalPy`. **Nothing here is submitted automatically** — a
human reviews, forks, and opens any PRs. The staging layout mirrors the upstream
repo so a contributor can copy each file to the same path in the fork.

## What's in here

| Path | Maps to upstream path | Purpose |
|---|---|---|
| `target_tools/archway/` | `src/target_tools/archway/` | Archway as a TypeEvalPy tool. Calls the hosted analysis API; engine internals stay server-side. Falls back to a local stub backend so the integration is exercisable today. |
| `runner_class_patch.py.add` | append into `src/runner_class.py` | New `ArchwayRunner` class registering the tool with the runner. |
| `main_runner_patch.py.add` | append into `src/main_runner.py` | Adds `archway` to the `available_runners` registry. |
| `.github/workflows/regenerate-leaderboard.yml` | same path | Standalone CI action that re-runs the deterministic baselines against current GT, regenerates the leaderboard markdown, and opens a PR with the result. Generic — no Archway assumptions. |

The two artifacts are independent. Either can be PR'd in isolation; the workflow is a **gift to the project** (the repo has no CI today and the published leaderboard hardcodes `EXPERIMENT_RUN_ON = "14 Jan 2024"`), while `target_tools/archway/` is the path for getting Archway onto the board.

## Build provenance

Every result emitted by `target_tools/archway/` is annotated against the benchmark
commit at the time of the run. Never compare numbers across different commits of
`micro-benchmark/`. The CI workflow records the GT commit hash in the PR body.

## Human steps to PR each artifact

### 1. `target_tools/archway/`

```bash
git clone https://github.com/secure-software-engineering/TypeEvalPy.git
cd TypeEvalPy
git checkout -b feat/add-archway-tool
cp -r <archway-benchmarks>/upstream/target_tools/archway/ src/target_tools/

# Apply the two .py.add patches by hand (small additions to existing files):
cat <archway-benchmarks>/upstream/runner_class_patch.py.add  # paste class into src/runner_class.py
cat <archway-benchmarks>/upstream/main_runner_patch.py.add   # add registry entry to src/main_runner.py

# Verify in stub mode (no API needed)
docker build -t archway src/target_tools/archway/
cd src
ARCHWAY_STUB_ACCURACY=0.67 python main_runner.py --runners archway

git add src/target_tools/archway src/runner_class.py src/main_runner.py
git commit -m "Add Archway as a TypeEvalPy tool"
gh pr create --title "Add Archway as a TypeEvalPy tool" --body-file <description>
```

PR description should call out:
- Container is a thin client; engine internals stay server-side (privacy / IP).
- Stub mode is for pipeline validation, not evaluation — must never be used to populate the public board.
- Schema mapping lives in `target_tools/archway/src/typeevalpy_mapping.py`, which is a byte-identical mirror of the harness's mapping module.

### 2. Regenerate-leaderboard workflow

```bash
cd TypeEvalPy
git checkout -b ci/regenerate-leaderboard
mkdir -p .github/workflows
cp <archway-benchmarks>/upstream/.github/workflows/regenerate-leaderboard.yml \
   .github/workflows/

git add .github/workflows/regenerate-leaderboard.yml
git commit -m "ci: regenerate the leaderboard against current GT"
gh pr create --title "ci: regenerate the leaderboard against current GT" \
             --body-file <description>
```

PR description should call out:
- No Archway-specific code; generic across all current tools.
- Deterministic tools by default; LLM runs gated behind an explicit `include_llms` input so re-runs stay cheap.
- Stamps the actual UTC run date into `EXPERIMENT_RUN_ON` so the board's footer is honest.
- Triggers on `workflow_dispatch` (manual) and on pushes that touch `micro-benchmark/**` or `src/result_analyzer/**` (any GT or scorer change).

## Guardrails for whoever PRs this

- **No secrets in commits.** The Archway API endpoint + key are read from env at runtime. The Dockerfile must not bake either in.
- **No leak of internals.** Nothing in `target_tools/archway/` reveals Archway's translation engine, analysis engine, categorical IR, or any non-public schema. The container is a thin HTTP client.
- **No silent zeros.** The runner exits with code 2 when no backend is configured — see `runner.py:_backend_or_die`. Empty result files would score as `0 / N` and quietly corrupt the leaderboard.
- **Lock the GT.** Every result must be tagged with the benchmark commit it was scored against. Mixing generations is the bug that motivated this whole effort.
- **Sync the mapping.** The harness CI enforces parity between `<archway-benchmarks>/src/archway_benchmarks/typeevalpy_mapping.py` and `target_tools/archway/src/typeevalpy_mapping.py`. If you change either, run `scripts/sync_upstream_mapping.py` and commit both.
