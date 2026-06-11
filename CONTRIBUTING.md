# Contributing to Archway Benchmarks

Thank you for your interest in contributing! This document covers development setup and the high-level shape for adding a new benchmark.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Adding a Benchmark](#adding-a-benchmark)
- [Pull Request Process](#pull-request-process)

## Getting Started

### Prerequisites

- Python 3.11 or higher
- Git
- The static analysis tools you want to benchmark against (installed in their own envs)

### Fork and Clone

```bash
git clone git@github.com:Archway-Labs-AI/archway-benchmarks.git
cd archway-benchmarks
git submodule update --init --recursive
```

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/ -v --tb=short
```

## Code Style

This repo uses standard Python conventions consistent with the rest of Archway:

- **Line length:** 100
- **Linter:** ruff (`ruff check src/`)
- **Type checker:** mypy
- **Target:** Python 3.11+

Run the lint suite before pushing:

```bash
ruff check src/ --select E,F,W
```

## Adding a Benchmark

Each integrated benchmark lives in two places:

- **The corpus and its official scorer** as a pinned git submodule under `extras/<name>/`. Vendoring keeps GT pinned to a known commit so scores are reproducible, and lets us re-run the official scorer rather than re-implementing it.
- **The harness adapter** under `src/archway_benchmarks/benchmarks/<name>.py` and `src/archway_benchmarks/scoring/<name>.py`. The adapter loads snippets into the harness's `Snippet`/`Annotation` model and wires the benchmark's own scorer behind the `Benchmark.score` API.

`extras/TypeEvalPy/` is the worked example — both the loader (`benchmarks/typeevalpy.py`) and the scorer wrappers (`scoring/typeevalpy.py`, `scoring/typeevalpy_lenient.py`) demonstrate the pattern.

Document new benchmarks in `docs/` with:

1. **Target** — what the benchmark measures and where it came from.
2. **Vendoring choice** — which upstream commit/fork the submodule pins to and why.
3. **Scoring** — which of the benchmark's scoring modes are wired in and how to invoke them via `archway-bench`.

`docs/BUGSINPY.md` is the worked example for those notes.

## Pull Request Process

1. Branch from `main` with a descriptive name (e.g. `feat/pycg-loader`).
2. Open a PR against `main` with a clear summary and test plan.
3. CI runs tests + ruff + gitleaks; all must pass.
