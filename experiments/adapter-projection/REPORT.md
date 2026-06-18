# Adapter projection: surface faithful `self.X` instance-attribute stores

**Goal:** `adapter-self-attr-and-classvar-projection`. The run-31 `classes`
LOCATION_MISS diagnosis
(`Archway-worktrees/engine-work/docs/design_notes/ENGINE-remaining-locationmiss.md`)
found that the engine **emits** `self.X` instance-attribute stores at exactly the
GT `(line,col)` with the correct type, but the **benchmark adapter** drops them.
This is a *readout* fix in `archway-benchmarks` (outside `sd_core`): make the
adapter surface bindings the engine genuinely computed. **No engine change.**

**Legitimacy stance (faithful readout, not benchmark-gaming):** every annotation
this change flips was first confirmed to correspond to a real engine binding —
a `self.<attr>` store at the GT position carrying the value the adapter then
projects. The change surfaces only what the engine already computed; it never
fabricates a prediction. Where the engine emits **nothing** at a GT position
(the class-body `class_var` sites), the adapter still returns nothing — those
remain LOCATION_MISS and are routed back to the engine as a genuine emission gap.

## Result (headline)

`classes` category, all 543 snippets, real engine → real adapter → real scorer:

| outcome | before | after | Δ |
|---|---:|---:|---:|
| EXACT | 5,239 | **5,439** | **+200** |
| TYPE_MISS | 101 | 65 | −36 |
| LOCATION_MISS | 260 | **96** | **−164** |
| SPURIOUS | 0 | 0 | 0 |

All **200** flips go to EXACT. **Zero regressions; SPURIOUS stays 0.** Of the
200: **164** were LOCATION_MISS→EXACT (the dropped attribute stores) and **36**
were a false TYPE_MISS→EXACT (container-valued attributes mis-projected to their
element type). Every one of the 200 was independently verified to sit on a real
`self.<attr>` engine binding at its GT position (`artifacts/flip_audit.json`).

## Method (reproduce-or-it-didn't-happen)

Worktree `feat/adapter-projection`; `.venv` = `python -m venv .venv && pip install -e '.[dev]'`
(plus `tqdm`, `prettytable` for the vendored lenient scorer).

1. **Engine confirmation (legitimacy guard).** Brought up the real analysis
   server on the pinned engine worktree
   (`Archway-worktrees/engine-work`, `sd_core.analysis_server`, port 8788) and
   fetched the `FinalizedAnalysis` JSON for all 543 `classes` snippets through
   the **production** `ArchwayAnalysisEngine` HTTP path (`harness.py fetch` →
   `artifacts/engine_classes.json`, 0 engine errors). The engine worktree HEAD
   (`e7250e2`) is 2 commits past the run-31 diagnosis base; the only change since
   is the **assignments** `*b`-position fix — `classes` attribute-store behaviour
   is untouched, so it reproduces run-31 for this category. Confirmed: the engine
   emits `self.child`/`self.width`/`self.a`/`self.c`/`self.instance_var` … at
   `engine_col + 1 == GT_col` with the correct element kind
   (callable / pytype / instance / list).

2. **Before/after (`harness.py score`).** The engine JSON is cached **once**;
   the before and after scores read the same cache and the real
   `score_snippet` + `check_match`, so the only variable between them is the
   adapter code. The **before** run reproduces the diagnosis exactly:
   260 LOCATION_MISS, of which the six attribute families sum to
   4+24+84+14+7+7 = **140** and `class_variable` = 120.

3. **Faithfulness audit (`artifacts/flip_audit.json`).** For all 200 flipped
   annotations, located the engine binding at the GT `(row, col)` and confirmed
   it is named `self.<tail>` where `<tail>` is the GT attribute's last component
   (`B.child`→`self.child`, `A.B.a`→`self.a`, `MyClass.instance_var[0]`→
   `self.instance_var`). **200/200 faithful, 0 unfaithful, 0 regressions.**
   The 96 remaining LOCATION_MISS are 100% `class_variable` `class_var` (and its
   subscripts) and have **no** engine binding at their position at all — the
   pure engine gap.

Re-run:
```sh
python -m venv .venv && .venv/bin/pip install -e '.[dev]' tqdm prettytable
# start engine server (separate worktree, no deps):
( cd ../Archway-worktrees/engine-work && PYTHONPATH=. python -m sd_core.analysis_server \
    --host 127.0.0.1 --port 8788 --repo-root . ) &
.venv/bin/python experiments/adapter-projection/harness.py fetch
.venv/bin/python experiments/adapter-projection/harness.py score --out experiments/adapter-projection/artifacts/score_before.json
# (apply the adapter edit)
.venv/bin/python experiments/adapter-projection/harness.py score --out experiments/adapter-projection/artifacts/score_after.json
```

## The bug and the fix

The engine names an instance-attribute store `self.attr`; GT names the same
site `ClassName.attr`. The adapter's `is_indirect` branch
(`_lookup_predicted_types`) first tries an exact whole-name match — which misses
(`self.attr` ≠ `ClassName.attr`) — then falls through to `_value_element`, which
extracts a *container's* element/value type:

```python
named = [b for b in matches if b.get("name") == loc.name]   # "self.child" != "B.child" → []
...                                                          # falls through to:
inner = _value_element(elt)                                  # only handles dict/list/tuple
```

`_value_element(callable | pytype | instance)` is `None` → the whole lookup
returns `None` → **LOCATION_MISS**. For a container-valued attribute
(`self.instance_var = [...]`), `_value_element(list)` returns the *element*
`int` instead of the attribute's own `list` → a **false TYPE_MISS**.

`_matches` is **position-only**, so a position match already establishes
identity. The fix splits the `is_indirect` branch by the GT name's accessor:

- **bare attribute** (`.` but no `[`): return the matched binding's **own**
  element via `_to_types` — recovers both the scalar/callable/instance stores
  (was LOCATION_MISS) and the container-valued ones (was false TYPE_MISS).
- **subscript** (`[`): unchanged — project the container's element via
  `_value_element`.

The decisive case is `class_variable`'s line 6, where **four** GT entries share
position (6,9): `MyClass.instance_var` (wants the container `list`) and
`MyClass.instance_var[0..2]` (want the element `int`). The `.`-vs-`[` split
routes them correctly off the single engine `self.instance_var = list[int]`
binding. (`tests/test_archway_adapter_self_attr.py::`
`test_attr_and_its_subscript_together_disambiguate_by_accessor`.)

The exact-name `named` path is kept as a first preference (it still serves any
binding the engine names with the full GT expression, e.g. the pre-existing
`self.smth` regression test).

## Faithful-but-dropped vs would-be-fabrication (audit)

| route | count | disposition |
|---|---:|---|
| **Adapter-fixable, faithful** — `self.X` store at GT pos, surfaced | **200** | now EXACT (164 ex-LOCATION_MISS + 36 ex-TYPE_MISS); each verified against a real `self.<tail>` binding |
| **Engine gap, NOT adapter-fixable** — class-body `class_var` w/ no positioned binding | **96** | stays LOCATION_MISS; routed back to engine (finalize must position class-body bindings) |

Per-family before→after (only changed families shown):

| family | EXACT | TYPE_MISS | LOCATION_MISS |
|---|---|---|---|
| abstract_class | 12→16 | 0→0 | 4→0 |
| base_class_attr | 372→414 | 18→0 | 24→0 |
| base_class_calls_child | 360→444 | 42→42 | 84→0 |
| class_variable | 234→276 | 18→0 | 120→**96** |
| nested_class_calls | 58→72 | 0→0 | 14→0 |
| self_assign_func | 51→58 | 0→0 | 7→0 |
| self_assignment | 37→44 | 0→0 | 7→0 |

**Two refinements to the diagnosis (both confirmed faithful):**

1. The diagnosis bucketed all 120 `class_variable` LOCATION_MISS as the
   class-body `class_var` engine gap. Measured: **96** are `class_var` (engine
   gap) and **24** are scalar `self.instance_var` stores the engine *does* emit
   — adapter-fixable. So the adapter-fixable LOCATION_MISS is **164**, not 140.
2. The diagnosis predicted the fix "also cleans the parallel false TYPE_MISS on
   container-valued attributes." Confirmed: **36** TYPE_MISS→EXACT
   (`base_class_attr` 18 + `class_variable` `instance_var` 18).

**Left untouched (correctly):**
- `base_class_calls_child` 42 TYPE_MISS are `A.func` **returns** (kind=`return`,
  handled by the callable-return branch, not this attribute path). They are an
  engine return-union precision matter, out of scope here.
- `imported_*` 23 TYPE_MISS and the 96 `class_var` LOCATION_MISS are engine
  coverage gaps — routed back, not gamed.

## Gate

- **Adapter unit tests (no-server, representative bindings):**
  `tests/test_archway_adapter_self_attr.py` — 11 tests covering callable/scalar/
  instance/container attribute stores, the doubly-dotted `A.B.a`, the
  attr-vs-subscript-at-same-position disambiguation, the engine-gap
  no-fabrication guard, and subscript/plain-variable regressions. Plus the
  pre-existing `tests/test_archway_adapter_routing.py` (5 tests) still green.
- **Before/after on `classes`:** above (+200 EXACT, −164 LOCATION_MISS, −36
  TYPE_MISS, 0 SPURIOUS), engine-confirmed faithful.
- **Full suite:** `pytest` → **98 passed**. Two `test_a1_a2_reference.py`
  autogen assertions were stale **before** this work (pinned `49,250/77,268` vs
  current corpus `49,206/77,223`) — they fail identically with this change
  reverted (the test drives a fixture-local adapter, not the production one).
  The corpus was re-derived in a prior `main` commit (`9afcfc9b`); the test
  docstring sanctions refreshing pinned numbers "when GT changes," so the two
  autogen totals were updated to the current corpus. This is an incidental
  stale-reference refresh, independent of the adapter projection.

## Follow-on (required)

The before/after used the engine worktree at `e7250e2` (2 commits past the
run-31 pin). A full corpus re-score on the canonical pinned engine
(`loop/main 3c2c784`) via `archway-bench iterate --engine-pin` should confirm
the category-wide lift in the run store. The 96 `class_variable` `class_var`
LOCATION_MISS are an **engine** finalize gap (position class-body bindings) —
route to `engine-work`, not this repo.

## Artifacts

- `artifacts/engine_classes.json` — raw `FinalizedAnalysis` for all 543 classes
  snippets (the "engine genuinely emits it" evidence).
- `artifacts/score_before.json` / `artifacts/score_after.json` — per-family,
  per-annotation outcomes before/after the adapter edit.
- `artifacts/flip_audit.json` — the 200-flip faithfulness audit (200/200 on a
  real `self.<tail>` binding; 0 regressions; 96 remaining LM all engine-gap).
- `harness.py` — the fetch/score driver.
