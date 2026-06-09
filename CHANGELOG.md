# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- TypeEvalPy benchmark (153 snippets / 850 annotations) vendored as a git submodule at `extras/TypeEvalPy/`.
- Engine `Protocol`s + stub trio (`StubTranslationEngine`, `StubAnalysisEngine`, `StubAnalysisResultAdapter`) with tunable accuracy `p` — full harness runs against stubs today.
- `Benchmark` / `AnalysisResultAdapter` ABCs with a concrete `TypeEvalPyBenchmark` (load + `to_tool_format` round-trip).
- Three-bucket per-annotation scoring (`EXACT` / `TYPE_MISS` / `LOCATION_MISS` / `SPURIOUS`) built on `extras/TypeEvalPy/src/result_analyzer` primitives — no metric re-implementation.
- Coverage model (`COVERED` / `PARTIAL` / `UNSUPPORTED`) with dual all-vs-covered scoring.
- SQLite-backed result store; CLI `run` / `score` / `runs` / `export` / `serve` / `manifest`.
- Corpus manifest generator (AST feature detection, import profile, payoff-curve slices; reproduces 399/550/732/95/150).
- FastAPI dashboard with Archway tokens: scores view, Braintrust-style inspector, per-snippet outcome marks, FP+callable target-set board, run-over-run compare.
- Hardcoded TypeEvalPy leaderboard at `leaderboard/typeevalpy.json` (from `vendor/.../paper_table_1.csv`).
- Initial repository scaffolding (README, LICENSE, CONTRIBUTING, pyproject, CI).
