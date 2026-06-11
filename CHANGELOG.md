# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed
- Team-internal benchmark workflow extracted to the private `Archway-Labs-AI/archway-bench-internal` package: `iterate` / `progress` / `report` subcommands, `engine_pin.py` (verified-pin worktree machinery), `reports.py` (per-run detail markdown writer), `test_engine_pin.py`, and the nine `scripts/bugsinpy_*.py` investigation probes. The public CLI now focuses on its actual purpose: score benchmarks, reproduce baselines, browse runs. Internal users install the sibling package: `pip install -e ../archway-bench-internal` → `archway-bench-i iterate ...`.

### Changed
- Public CLI surface is now: `run` / `score` / `runs` / `export` / `serve` / `manifest` / `regenerate-baselines` / `baselines-report` / `bugsinpy-*` (manifest|detect|repair|progress|bucket|adjudicate|bucket-report|flagger).
- Submodule renamed from `vendor/TypeEvalPy/` to `extras/TypeEvalPy/` and retargeted to the `Archway-Labs-AI/TypeEvalPy` fork (our own modifications live on feature branches there; `main` tracks upstream).
- CONTRIBUTING.md rewritten to describe the actual benchmark layout (`extras/<name>/` + adapter under `benchmarks/<name>.py`); the unused `suites/` scaffold removed.
- Python version baseline tightened to 3.11+ across pyproject, README, CONTRIBUTING, and CI.
- License declaration in pyproject corrected from MIT to Apache-2.0 to match LICENSE / NOTICE / README.

### Added
- BugsInPy benchmark machinery (parallel to TypeEvalPy; **machinery only — nothing run, classified, or scored**): submodule declaration at `extras/BugsInPy/`, a per-bug loader (`benchmarks/bugsinpy.py`) exposing project / commits / patch-derived bug locations / failing tests / fix-shape metadata, a **both-modes scorer** (`scoring/bugsinpy.py` — detection vs. known location, repair via test-suite-passes), a repair-runner engine seam (`engines/bugsinpy.py`), `store.py` `bugsinpy_*` tables sharing `runs` with provenance (mode/engine_sha/corpus_commit/subset), a progress report (`bugsinpy_report.py`), a metadata-only manifest (`bugsinpy_manifest.py`), and CLI `bugsinpy-manifest|detect|repair|progress`. See `docs/BUGSINPY.md`.
- BugsInPy **DIRECTIONAL bucketer** (`bugsinpy_bucketer.py`; diagnostic, **not claim-grade**): patch-evidenced bug class (`none_or_null` / `type_check` / `missing_branch` / `exception_handling` / `api_misuse_lib` / `other`) with per-bug `confidence` (high/low) + `BUCKETER_VERSION`; stored re-computably keyed by `(bug_key, version)` in `bugsinpy_buckets` so re-running re-buckets stored detection results WITHOUT a benchmark re-run; detection rate reportable × class; low-confidence + `api_misuse_lib` surfaced as a needs-adjudication queue. CLI `bugsinpy-bucket|adjudicate|bucket-report`.
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
