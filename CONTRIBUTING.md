# Contributing to Archway Benchmarks

Thank you for your interest in contributing! This document covers development setup and how to add a new benchmark suite.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Adding a Benchmark Suite](#adding-a-benchmark-suite)
- [Pull Request Process](#pull-request-process)

## Getting Started

### Prerequisites

- Python 3.9 or higher
- Git
- The static analysis tools you want to benchmark against (installed in their own envs)

### Fork and Clone

```bash
git clone git@github.com:gocon-loca/archway-benchmarks.git
cd archway-benchmarks
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

This repo uses the same conventions as [Archway](https://github.com/gocon-loca/archway):

- **Line length:** 100
- **Linter:** ruff (`ruff check src/`)
- **Type checker:** mypy
- **Target:** Python 3.9+

Run the lint suite before pushing:

```bash
ruff check src/ --select E,F,W
```

## Adding a Benchmark Suite

Create a new directory under `suites/<short-name>/` with:

```
suites/<name>/
├── README.md              # overview, target version, bug class
├── expected.json          # ground-truth Archway findings
├── cached-results/        # gitignored — raw tool JSON
│   ├── bandit.json
│   ├── mypy.json
│   └── pylint.json
└── tools/                 # human-readable summaries
    ├── bandit-results.md
    ├── mypy-results.md
    └── pylint-results.md
```

Document in the suite's `README.md`:

1. **Target** — the OSS project and exact version/commit.
2. **Bug class** — what kind of bug this suite tests for.
3. **Tool commands** — exact invocations used to produce each `cached-results/*.json`.
4. **What conventional tools miss** — one paragraph per tool explaining the gap.

## Pull Request Process

1. Branch from `main` with a descriptive name (e.g. `suite/django-orm-leaks`).
2. Commit suite content + tool result summaries; do not commit `cached-results/*.json`.
3. Open a PR against `main` with the suite's README excerpt as the PR description.
