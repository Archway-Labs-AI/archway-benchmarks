<p align="center">
  <img src="docs/assets/logo-placeholder.svg" alt="Archway Benchmarks Logo" width="120" height="120">
</p>

<h1 align="center">Archway Benchmarks</h1>

<p align="center">
  <strong>Static Analysis Benchmark Suites for Archway's Categorical IR</strong>
</p>

<p align="center">
  <em>"Show me what conventional tools miss — and what categorical analysis catches."</em>
</p>

<p align="center">
  <a href="https://github.com/gocon-loca/archway-benchmarks/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.9%2B-blue" alt="Python 3.9+"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> |
  <a href="#suites">Suites</a> |
  <a href="#methodology">Methodology</a> |
  <a href="#contributing">Contributing</a>
</p>

---

## Why Archway Benchmarks?

Archway compiles source code into a **categorical intermediate representation**, enabling precise queries about structure, data flow, and side effects that conventional static analysis tools cannot express. This repository collects **benchmark suites** that contrast tool-level findings (syntax, types, lint rules) against Archway's deeper semantic analysis.

Each suite targets a real-world codebase with a known class of bugs, runs the standard tools (mypy, pylint, bandit, semgrep, pyright, etc.), and records exactly what each one finds — and misses.

---

## Quick Start

```bash
# Clone
git clone git@github.com:gocon-loca/archway-benchmarks.git
cd archway-benchmarks

# Install
pip install -e ".[dev]"

# Run a suite
archway-bench run zipline-demo
```

---

## Suites

| Suite | Target | Bug Class | Status |
|-------|--------|-----------|--------|
| _coming soon_ | — | — | — |

Each suite lives under `suites/<name>/` and contains:

- `README.md` — overview, target version, the bug class under test
- `cached-results/` — raw JSON output from each tool (gitignored)
- `tools/` — human-readable result summaries per tool
- `expected.json` — the ground-truth findings Archway should produce

---

## Methodology

1. **Pick a target** — a real OSS codebase with a documented bug or class of bugs.
2. **Run baseline tools** — mypy, pylint, bandit, semgrep, pyright, etc. on the unmodified target.
3. **Record findings** — both raw JSON and a human-readable summary per tool.
4. **Define the gap** — what the bug class is, why each tool missed it, what Archway should catch.
5. **Run Archway** — compare against the cached baselines.

Cached results are gitignored to keep the repo small; the README in each suite documents the exact command and tool versions used.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and how to add a new suite.

---

## License

MIT — see [LICENSE](LICENSE).
