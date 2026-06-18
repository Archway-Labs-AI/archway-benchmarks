# Benchmark-adapter fix — subscript dict/list value/element projection

**Goal:** `adapter-subscript-dict-value-projection` (benchmark-adapter, NOT engine).
Same adapter (`src/archway_benchmarks/benchmarks/archway_adapter.py`) and the same
READOUT-faithfulness discipline as the `self.X` goal: surface only a value/element type
the engine **genuinely computed**; never invent one.

## TL;DR

The batch-2 note (`ENGINE-dict-list-precision.md`) flagged the adapter's subscript/value
projection as *"the dominant adapter lever"*: the engine's container binding carries keyed
(`DictType.slots`) / positional (`ListType.slots`) per-key precision, but the old
`_value_element` projected only the **homogeneous** value/element join — so every
heterogeneous-slot read (`d['a']`, `a[0]`, `d['a']['b']`) over-unioned into a TYPE_MISS.

Taught the adapter to parse the literal `[k][k2]...` chain off the GT name and walk it
through the engine's slots. On the **dicts + lists** corpus (1472 snippets, real live
analysis server → real adapter → real scorer), the subscript bucket moves:

| outcome | before | after | Δ |
|---|---:|---:|---:|
| EXACT | 10644 | **11214** | **+570** |
| TYPE_MISS | 1038 | 252 | −786 |
| LOCATION_MISS | 183 | 399 | +216 |
| SPURIOUS | 0 | 0 | 0 |

**The clean split (the success criterion):**

- **570** subscript GT entries are **adapter-projectable faithfully** — every one flips
  TYPE_MISS → EXACT, and every flip was audited to sit on a **populated engine slot**
  (0 fabricated).
- **651** are **empty-/no-slot ENGINE gaps**, routed back unchanged (the engine carries no
  keyed precision through `|`-merge / `merge` / `zip` / inter-proc const-key / nested
  strong-update). The adapter leaves these honest misses; it does **not** paper over them.
- **0** EXACT → non-EXACT **regressions**.

The `plain`-name bucket (real bindings, not subscripts) is untouched: EXACT 11335,
TYPE_MISS 188, both before and after.

---

## Method (reproduce-or-it-didn't-happen)

- **Engine pin:** Archway analysis server from worktree `engine-work` @ `a188323`
  (`loop/engine-work`), launched `hatch run analyze --port 8788`. Serialized dict/list
  elements carry `slots` (keyed `[[k, v], ...]` for dict; positional `[v, ...]` for
  list/tuple) per `sd_core/analysis/types/lattice/serde.py:152-173`.
- **Corpus:** `extras/TypeEvalPy/autogen_typeevalpy_benchmark/python_features/{dicts,lists}`
  — 1472 snippets, **0 engine errors**.
- **Harness:** `experiments/adapter-projection/harness_subscript.py`, two phases split so
  before/after differ **only** by adapter code:

  ```bash
  # one-time: capture raw FinalizedAnalysis JSON from the live server (adapter-independent)
  .venv/bin/python experiments/adapter-projection/harness_subscript.py fetch
  # score with the CURRENT adapter, then again after the edit (same cached engine JSON)
  .venv/bin/python experiments/adapter-projection/harness_subscript.py score \
      --out experiments/adapter-projection/artifacts/score_sub_before.json
  # (apply the adapter fix)
  .venv/bin/python experiments/adapter-projection/harness_subscript.py score \
      --out experiments/adapter-projection/artifacts/score_sub_after.json
  ```

  A GT annotation is bucketed `subscript` iff its name contains `[` (`d['a']`, `a[0]`,
  `d['a']['b']`); else `plain`. Scoring uses the real `score_snippet` + the vendored
  TypeEvalPy `check_match` (exact normalized set-equality — a predicted **superset**
  is a TYPE_MISS, which is exactly why the homogeneous over-union loses).

Raw evidence committed under `artifacts/`:
`engine_dicts_lists.json` (1472 snippets of raw engine output),
`score_sub_before.json`, `score_sub_after.json`, `subscript_flip_audit.json`.

---

## The fix (`archway_adapter.py`, +109/−3)

Pure readout code in `archway-benchmarks` (outside `sd_core`). The subscript branch of
`_lookup_predicted_types` now parses the GT name and walks the engine's slots:

- **`_subscript_keys(name)`** — `ast.parse` the GT name and peel the trailing
  `[k][k2]...` chain into a base-first list of **literal** keys. Returns `None` (→ fall
  back to the old single-level homogeneous `_value_element`) when the name has no
  subscript, won't parse, or any index is **non-literal** (a variable index / slice — not
  slot-projectable). Each literal's Python **type is preserved**, so int `1` (`d[1]`) and
  str `'1'` (`d['1']`) match **distinct** engine slot keys. Handles a negative-int literal
  (`a[-1]` parses as `USub` over a constant).
- **`_project_slots(elt, keys)` / `_index_one(elt, key)`** — walk the chain. At each
  level: a **dict** returns the slot whose literal key matches *exactly* (same Python type
  **and** value), else its homogeneous `value`; a **list/tuple** returns the positional
  slot at an int index (negatives wrap), else its homogeneous `element`. Anything else
  (a **`union`** / scalar / **`bottom`** base) → `None`: the engine carries no projectable
  container there, so the read projects nothing and the GT keeps its honest miss.

Faithfulness invariants this preserves:

- It surfaces **only** engine-computed values — a populated slot (proven per-key precise
  in `ENGINE-dict-list-precision.md`) or the engine's own homogeneous join. Never a
  synthesized type.
- A populated slot **strengthens** precision (over-union → exact); an absent slot keeps
  the prior homogeneous fallback (no regression); a `union`/`bottom` base or an
  unreachable deeper level projects **nothing** (an engine gap stays a miss).

`_matches` (the col 1-index conversion `engine_col + 1 == gt_col`) was audited and is
**correct as-is** — the 10644 already-EXACT subscript reads prove the base bindings match
at the GT position; no footgun. The `_lookup_predicted_types` indirect-name split
(`"[" in loc.name`) correctly routes subscript names to this path.

---

## Results — the full transition matrix (subscript bucket, 11865 GT entries)

Re-derived per-GT from the cached engine output (`subscript_flip_audit.json`):

```
before          ->  after            count
EXACT           ->  EXACT            10644
TYPE_MISS       ->  EXACT              570   <- adapter-projectable (slot-backed)
TYPE_MISS       ->  TYPE_MISS          252   <- engine gap (dict no-slots)
TYPE_MISS       ->  LOCATION_MISS      216   <- engine gap (|-merge nested union)
LOCATION_MISS   ->  LOCATION_MISS      183   <- engine gap (union/bottom/unpositioned)
EXACT           ->  non-EXACT            0   <- ZERO regressions
```

### The 570 flips — faithfulness audit

Every TYPE_MISS → EXACT flip was re-checked against the raw engine output: **570 / 570**
consulted a **populated engine slot** whose projected type equals the GT (= CPython truth,
since the vendored `check_match` scores against the CPython-derived GT). 0 not-slot-backed.

End-to-end through the real adapter, `dicts/call_1_31_dict_int`
(`d = {"a": func1, 1: func2, 2: 3}` — int **and** str keys in one dict; homogeneous value
`union(callable, int)` TYPE_MISSed all three before):

```
d['a']  exp=callable  pred=callable  EXACT   (str slot 'a')
d[1]    exp=callable  pred=callable  EXACT   (int slot 1)
d[2]    exp=int       pred=int       EXACT   (int slot 2)
```

### The 651 engine gaps — routed back, not papered over

| cluster | count | after-outcome | why it's an ENGINE gap |
|---|---:|---|---|
| dict **no-slots** via `\|`-merge / `merge` / `zip` | 252 | stays TYPE_MISS | engine drops keyed slots through these ops; only the homogeneous `value` (an over-union) survives — the adapter surfaces *that*, an honest wrong-by-over-approximation, not a fabricated per-key answer |
| `merge_pipe` **nested union** (`merged_dict['b'][0]`) | 216 | TYPE_MISS → LOC_MISS | level-1 resolves to a genuinely heterogeneous `union(dict,list)`/`union(bool,dict)`/… (the `\|`-merge gap); the deeper read is undefined → project nothing. The old one-level code answered the *wrong depth* (a structurally-wrong TYPE_MISS); removing it **improves completeness** |
| `param_key` **union base** (`f[0]`, `f['k']`) | 162 | stays LOC_MISS | `f = func(key)` reading `d[key]` — engine returns a `union` of the possible containers (inter-proc const-key unresolved); not a single projectable container |
| `nested` **unpositioned rebind** (`d['a']['b']`) | 12 | stays LOC_MISS | nested SUBSCRIPT_SET deferred to the aliasing functor → no binding emitted at the GT read site |
| `new_key_param` **bottom base** (`e[0]`, `e['k']`) | 9 | stays LOC_MISS | inter-proc dict mutation → `e` is `bottom` (engine computed nothing — a genuinely empty slot) |

Accounting closes exactly: `570 + 252 + 216 + 162 + 12 + 9 = 1221 = 1038 TYPE_MISS + 183
LOCATION_MISS` (the entire before-state subscript miss set). Every one of the 651 residual
gaps maps to a cluster the engine-side note already diagnosed and routed as harder
follow-up (`\|`/merge/zip slot-carry, inter-proc const-key, nested strong-update).

---

## Gate

- **Adapter unit tests:** `tests/test_archway_adapter_subscript.py` — **12/12** no-server
  tests on representative engine shapes (keyed dict precision, int-vs-str distinct slots,
  positional list slots, negative index, nested `d['a']['b']`, list-of-dicts
  `data[0]['name']`, no-slots homogeneous fallback, union-base → nothing, wrong-position
  guard).
- **Full archway-benchmarks suite:** `.venv/bin/python -m pytest -q` → **110 passed**
  (was 98 at the self-attr commit; +12 new). 0 regressions.
- **Before/after:** subscript EXACT **10644 → 11214 (+570)**, TYPE_MISS 1038 → 252,
  SPURIOUS 0 → 0; `plain` bucket unchanged; **0** EXACT → non-EXACT.
- **No `sd_core` change** — readout-only fix in `archway-benchmarks`.

## Files

- `src/archway_benchmarks/benchmarks/archway_adapter.py` — the fix (+109/−3).
- `tests/test_archway_adapter_subscript.py` — 12 no-server unit tests.
- `experiments/adapter-projection/harness_subscript.py` — fetch/score harness.
- `experiments/adapter-projection/artifacts/{engine_dicts_lists,score_sub_before,score_sub_after,subscript_flip_audit}.json`
  — raw engine evidence + before/after scores + the audited transition matrix.
