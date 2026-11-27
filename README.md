<div align="center">

<img src="assets/archway-wordmark.png" alt="Archway" width="260">

### Benchmarks

**Don't trust blindly. Trust and verify.**

The evaluation harness for Archway: measuring provable code analysis against published
static-analysis benchmarks, and re-running the field on current ground truth so every number is
honest and comparable.

[![License](https://img.shields.io/badge/license-Apache--2.0-1f3a5f)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-1f3a5f)](https://www.python.org/)
[![Archway](https://img.shields.io/badge/archway--labs.ai-0a66c2)](https://archway-labs.ai)

</div>

---

## What this is

AI now writes a large share of code, and we trust AI to review it. [Archway](https://archway-labs.ai)
is the verification layer that's missing: it turns real code into a precise mathematical object and
runs deterministic analysis on top, producing results you can check rather than text that sounds
right.

This repository is the harness we use to hold ourselves to that claim. It runs Archway's analysis
against established benchmarks, scores it with each benchmark's own scorer, and regenerates the
competitor baselines on the current ground truth so the comparison is like-for-like rather than
against a stale published table.

The Archway translation and analysis engines are not in this repository. The harness runs them in
process from an explicit engine checkout, and ships stub backends so the full pipeline runs
without them. Comparisons pin both the engine and the harness revision.

## Why baselines get regenerated

Published leaderboards drift: ground truth gets corrected, scoring semantics change, and tool and
model versions move on. This harness re-runs the deterministic baselines on the exact benchmark
commit it scores against, records the provenance (commit, date, versions) next to every number, and
separates current results from historical ones. Comparing on a shared, current answer key is the
point.

## What it does

- Pluggable benchmarks behind a small `Benchmark` abstraction.
- Like-for-like scoring that reuses each benchmark's official scorer.
- Per-annotation diagnostics: every prediction is tagged `EXACT`, `TYPE_MISS` (right place, wrong
  type), or `LOCATION_MISS` (coordinate/format mismatch), so a wrong number says whether it's an
  analysis problem or a plumbing problem.
- A rule-bucketed scoreboard: scores broken down by inference rule and annotation kind.
- An inspector and dashboard to browse examples, filter, and compare runs.

## Benchmarks

| Benchmark | Status |
|-----------|--------|
| [TypeEvalPy](https://github.com/secure-software-engineering/TypeEvalPy) (micro + autogen) | Supported |
| [PyCG](https://github.com/vitsalis/PyCG) (micro + macro) | Supported; needs the corpus and an engine checkout |
| TypyBench | Prediction and scoring implemented; needs the corpus and scorer setup |

## Quickstart

```bash
# Clone and pull the benchmark sources
git clone git@github.com:Archway-Labs-AI/archway-benchmarks.git
cd archway-benchmarks
git submodule update --init --recursive

# Install the harness (Python 3.11+)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run end-to-end against the stub engine — no Archway API required.
# Produces a full run in runs.db that the dashboard reads from.
archway-bench run --benchmark typeevalpy --engine stub --stub-accuracy 0.85 --seed 1

# List runs, show scores, or export a run's predictions in the benchmark's tool format
archway-bench runs
archway-bench score 1
archway-bench export 1 --output-dir export/

# Launch the dashboard (FastAPI; opens at http://127.0.0.1:8088)
archway-bench serve

# Regenerate competitor baselines on the current ground truth (requires Docker)
archway-bench regenerate-baselines --tools headergen jedi scalpel --benchmarks micro

# Write the human-readable findings report from the runs in the store
archway-bench baselines-report
```

The in-process engine backend is `src/archway_benchmarks/engines/successor_archway.py`; the PyCG
runner is `src/archway_benchmarks/pycg.py`. Initialize the TypeEvalPy submodule before using the
CLI, because its scorer is imported at start-up.

## Attribution

Benchmark suites and their scorers belong to their authors and are used under their respective
licenses; see [NOTICE](NOTICE). This project builds on
[TypeEvalPy](https://github.com/secure-software-engineering/TypeEvalPy) (Apache-2.0).

## License

[Apache-2.0](LICENSE) (c) Archway Labs.

---

<div align="center">

**[archway-labs.ai](https://archway-labs.ai)** | [Blog](https://archway-labs.ai/blog) | [Get in touch](https://archway-labs.ai/contact)

*AI writes your code. Archway proves it's correct.*

</div>

### Access and run data

Running the public benchmark harness does not require an Archway account. Local
backends require the relevant tool to be installed and available separately.
Using Archway's hosted engine requires both an authenticated identity and permission
from the service; copying this repository or registering an account grants neither.
Hosted access is currently team-only, with no public self-service access promised.

Hosted analysis is not wired into these harnesses at present (the session adapter used routes
retired in phase 5 of the engine's serving work); runs use a local engine worktree. Local
journals and detailed results may contain sensitive information.
No adapter automatically publishes these files. Keep source, checkpoints, journals
and detailed results private unless deliberately approved for publication. A future
public results page will publish selected scores and reproducibility metadata through
an explicit publication process, independently of executing or saving a run.
