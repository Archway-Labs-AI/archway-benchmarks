<p align="center">
  <img src="docs/assets/logo-placeholder.svg" alt="Archway Benchmarks Logo" width="120" height="120">
</p>

<h1 align="center">Archway Benchmarks</h1>

<p align="center">
  <strong>A modular harness for benchmarking Archway against published static-analysis leaderboards.</strong>
</p>

<p align="center">
  <em>"Where conventional tools punt, we can see exactly how — annotation by annotation."</em>
</p>

<p align="center">
  <a href="https://github.com/gocon-loca/archway-benchmarks/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.9%2B-blue" alt="Python 3.9+"></a>
</p>

---

## What this is

A harness that:

- **Wraps a published benchmark's scorer** (Layer A — comparability) so Archway's analysis engine looks like just another tool to the upstream scorer; no metric re-implementation.
- **Adds an inspection workflow** (Layer B — experience) on top: per-annotation outcomes, coverage-aware scoring, a corpus manifest, a Braintrust-style inspector, target-set boards, and run-over-run diffs.

The harness runs **end-to-end against stubs today**, so the dashboard and scoring loop are validated before any real engine plugs in.

### First benchmark: TypeEvalPy

Python type-inference micro-benchmark (153 snippets · 850 annotations · 18 categories). Vendored as a git submodule at `vendor/TypeEvalPy/` so the upstream scorer is reused verbatim.

---

## Quick start

```bash
git clone git@github.com:gocon-loca/archway-benchmarks.git
cd archway-benchmarks
git submodule update --init --recursive
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run the stub at 67% per-annotation accuracy (≈ HeaderGen-shaped numbers).
archway-bench run --stub-accuracy 0.67 --seed 1

# Re-generate the corpus manifest.
archway-bench manifest

# Start the dashboard.
archway-bench serve
# -> open http://127.0.0.1:8088
```

---

## Architecture

### Two layers

| Layer | What it does | Where it lives |
|---|---|---|
| **A · Comparability** | Emit predictions in TypeEvalPy's per-snippet `main_result.json` shape; reuse `vendor/TypeEvalPy/src/result_analyzer` primitives (`is_same_element`, `format_type`, `check_match`) for scoring. | `benchmarks/typeevalpy.py` (`to_tool_format`) + `scoring/typeevalpy.py` |
| **B · Experience** | Per-annotation outcomes (EXACT / TYPE_MISS / LOCATION_MISS / SPURIOUS), coverage-aware scoring, manifest, store, inspector, target-set board, run-compare. | The rest of the package |

### Engine boundary (opaque)

```python
class TranslationEngine(Protocol):
    def translate(self, source: str, path: str) -> Translation: ...

class AnalysisEngine(Protocol):
    def analyze(self, translation: Translation) -> AnalysisResult: ...
```

`Translation` and `AnalysisResult` are deliberately `Any`. **Only an `AnalysisResultAdapter` knows their shape.**

#### Stubs

```python
from archway_benchmarks.engines.stubs import make_stub_pair

translator, analyzer, adapter = make_stub_pair(snippets, accuracy=0.67, seed=42)
```

The stub analyzer takes ground truth as a hidden constructor input and emits predictions perturbed at `accuracy`. The GT-shortcut is quarantined in `make_stub_pair`; **no real-engine code path can touch it.**

### Three-bucket outcomes (the headline)

| Outcome | Meaning |
|---|---|
| `EXACT` | Location matched **and** normalized type set matched. |
| `TYPE_MISS` | Location matched, type set differed. **Functor bug.** |
| `LOCATION_MISS` | We emitted nothing at the GT key. **Translation/coordinate plumbing bug.** |
| `SPURIOUS` | We emitted a prediction at no GT location. Hurts soundness. |

These are persisted per annotation in the SQLite store — the inspector filters on them.

### Coverage model

Per-snippet translation status: `COVERED` / `PARTIAL` / `UNSUPPORTED`. Dashboard shows two scores side by side:

- **All** — leaderboard-comparable (over the whole corpus, missing snippets count as `LOCATION_MISS`)
- **Covered** — honest claim ("of what our translation reaches, we score X")

With the stub trio, everything is `COVERED`.

### Corpus manifest

`corpus_manifest.json` is generated from the vendored corpus:

```
153 snippets, 850 annotations
  minimal floor: 59 snippets, 399 anns (46.9%)
  +classes:      89 snippets, 550 anns (64.7%)
  no imports:    116 snippets, 732 anns (86.1%)
  function parameters: 95 anns
  callable GT:         150 anns
```

Per-snippet records carry AST-detected features (`class`, `lambda`, `comprehension`, ...), import profile (`none`/`stdlib`/`local_fixture`/`external_lib`), and payoff-curve slice flags. Per-annotation records carry `is_function_parameter` and `is_callable_gt`.

### Result store

SQLite (`runs.db`) with tables: `runs`, `snippets`, `annotations`, `spurious`, `scores`. Queryable; the dashboard reads directly. Two `scores` rows per run (`scope = all | covered`).

### Dashboard

FastAPI + Jinja2 + Tailwind (CDN). Branded with Archway tokens: navy `#1a2744`, orange `#e8742c`, cyan `#3bb3e8`, paper `#FAF9F5`, Inter for body, JetBrains Mono for stamps. No dark mode (matches the website).

Pages:
- `/` — runs list
- `/runs/{id}` — scores: us vs leaderboard, per-kind, per-category, both all + covered
- `/runs/{id}/inspect` — corpus annotation table with filters
- `/runs/{id}/snippets/{suite_path}` — per-snippet inspector (source + outcome marks)
- `/runs/{id}/targets` — FP + callable target-set board
- `/runs/{id}/compare/{other_id}` — run-over-run diff

---

## CLI reference

```
archway-bench run        --benchmark typeevalpy --engine stub --stub-accuracy 0.67 --seed N --db runs.db
archway-bench score      <run_id>
archway-bench runs       --db runs.db
archway-bench export     <run_id> --output-dir export/       # TypeEvalPy main_result.json files
archway-bench serve      --host 127.0.0.1 --port 8088
archway-bench manifest   --output corpus_manifest.json
```

---

## Adding a benchmark

1. **Vendor it** under `vendor/<name>/` (submodule preferred).
2. **Implement `Benchmark`** at `src/archway_benchmarks/benchmarks/<name>.py`:
   - `load() -> list[Snippet]`
   - `ground_truth() -> dict[Location, frozenset[str]]`
   - `to_tool_format(predictions)` — emit the upstream tool-output shape
   - `score(predictions) -> Scores` — delegate to `scoring/<name>.py`
3. **Write a scoring module** at `scoring/<name>.py` that **reuses the upstream scorer's primitives.** Three-bucket outcomes (EXACT / TYPE_MISS / LOCATION_MISS / SPURIOUS) must be preserved.
4. **Add a leaderboard JSON** at `leaderboard/<name>.json` (hardcoded competitor scores from the upstream paper/CSV — cite the source file).
5. **Register** the benchmark in `cli.py`'s `BENCHMARKS` dict.
6. **Write an adapter** per (benchmark, engine) at `benchmarks/<your_adapter>.py` — the *only* code that knows your engine's output shape.

---

## Don'ts

- Don't implement the translation or analysis engines here.
- Don't assume any shape for `Translation` / `AnalysisResult` outside an Adapter.
- Don't re-implement `exact`, `sound`, `complete`, or any other upstream metric. Wrap the upstream scorer; cite source paths.
- Don't collapse `LOCATION_MISS` and `TYPE_MISS` into one bucket — that distinction is the headline of the inspector.
- Don't let the stub's ground-truth shortcut leak into a real-run path. It's wired only via `make_stub_pair()`.

---

## License

MIT — see [LICENSE](LICENSE).
