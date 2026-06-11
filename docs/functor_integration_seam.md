# Functor integration seam — what the engine integrator will see on first plug-in

> **Adapter contract — col_offset is 1-indexed.**
> TypeEvalPy's GT files index `col_offset` starting at 1 (the first character of the
> annotation's name). Python's `ast.parse` returns 0-indexed `col_offset`. When the
> real engine produces annotations, the adapter is the place that translates engine
> coordinates → harness `Location.col` and that must add 1 if the engine reports
> ast-style columns. An off-by-one here produces silent `LOCATION_MISS` on every
> annotation under the strict scorer.
>
> The convention is pinned by `tests/test_typeevalpy_col_convention.py` (empirically
> verified against the vendor corpus). The stub already inherits GT's coordinates and
> scores 850/850 under both strict and lenient — see `tests/test_stub_dual_scorer.py`.

---



> One paragraph + a screenshot description. If the test suite passes
> (`pytest tests/test_functor_seam.py`), the picture below is what the
> dashboard's inspector will show the first time the real analysis engine
> emits results.

When the stub engines are swapped for the real translation/analysis pair, every
annotation in the dashboard's inspector falls into one of four buckets — and
the colour and column already disambiguate **plumbing bugs** (a wrong
file/line/col/name landed at the right type-set: `LOCATION_MISS`) from
**functor bugs** (right location, wrong type: `TYPE_MISS`). If the engine
mis-counts columns by one — the single most likely first failure — the
dashboard will show a `LOCATION_MISS` row whose `Expected` and `Predicted`
type cells are *identical*, which reads as "we got the type right but the
coordinate plumbing missed." That one display detail is what lets the
integrator fix the right thing within minutes.

## What the inspector renders, by bucket

- `EXACT` (cyan pill) — both location and types match.
- `TYPE_MISS` (orange pill) — location matched, type set wrong. **Functor work.**
- `LOCATION_MISS` (slate pill) — no prediction at the GT key. **Plumbing
  / coordinate / naming work.** If `Predicted` and `Expected` cells display
  the same value, the diagnosis is "right type but wrong place" and you
  should look at the adapter's coordinate mapping, not the engine.
- `SPURIOUS` (in the per-snippet view, listed under "Spurious predictions")
  — an emission with no matching GT location. Hurts soundness. Often a
  byproduct of a coordinate mismatch elsewhere.

## How the seam test reproduces this

`tests/test_functor_seam.py` builds an `ArchwayAnalysisResult` (see
`tests/fixtures/archway_fixture.py`) — the agreed engine output contract — for
the `args/multiple` snippet with the following planted defects:

| Planted defect | Expected bucket |
|---|---|
| `my_sum` return at col 4 instead of col 5 | `LOCATION_MISS` |
| `func` return at line 12 instead of line 11 | `LOCATION_MISS` |
| `func`'s parameter `a` reported as `x` | `LOCATION_MISS` |
| `my_sum`'s parameter `a`: right location, type `str` instead of `int` | `TYPE_MISS` |
| All other 6 annotations: correct | `EXACT` |

The test drives the fixture through the real Runner → real
`ArchwayAnalysisResultAdapter` → real scorer (which calls upstream
`result_analyzer` primitives) → the same SQLite store the dashboard
reads. Every assertion is on the persisted bucket value, not an
in-memory shortcut. If anything regresses about the adapter's coordinate
discipline or the scorer's `is_same_element` predicate, the seam test
fails before the real engine ever gets plugged in.

## Clean A1+A2 reference fixture — your first-pass target

`tests/test_a1_a2_reference.py` runs a clean reference that correctly
predicts every A1 (int/str) and A2 (callable) GT annotation in the corpus
and leaves A3–A5 unpredicted. Numbers are **pinned**:

| Benchmark | EXACT (strict & lenient) | Per-kind |
|---|---:|---|
| **micro** | **660 / 850** (77.6%) | FR=197, FP=88, LV=375 |
| **autogen** | **48,880 / 76,844** (63.6%) | FR=5,326, FP=666, LV=42,888 |

The strict and lenient scorers agree exactly because the reference
inherits GT's 1-indexed col_offset — confirming the convention end-to-end.

### How to use it

When your real expression-typer's first pass lands:

- **Below the fixture's EXACT count** → the gap is in your *rule logic*
  (your A1/A2 inference is missing real cases).
- **At or above the fixture** → the rule logic is sound; if any gap to
  HeaderGen remains, look at A3–A5 next.

The dashboard's rule-bucket scoreboard (`/runs/<id>`) cross-tabs your
caught annotations by A1–A5 × kind. Watch A1 and A2 to confirm the first
pass; A3–A5 columns are zero until you wire the later passes.

## Inspector URL on a real run

After the first real run lands as `#<id>`, open:

```
/runs/<id>/inspect?outcome=LOCATION_MISS    # only plumbing failures
/runs/<id>/inspect?outcome=TYPE_MISS        # only functor failures
/runs/<id>/snippets/args/multiple           # per-snippet view with coloured marks
```

The marks in the per-snippet source view are positioned at the GT
coordinates; a `LOCATION_MISS` dot at a line means we either emitted at the
wrong line or didn't emit at all — both diagnosed by the right-hand table.
