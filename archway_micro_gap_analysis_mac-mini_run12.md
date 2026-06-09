# Micro Type-Analysis Gap Analysis — Run #12 (post adapter-fix)

_Engine worktree `loop/nightly-20260609-0826` · TypeEvalPy micro-benchmark (153 snippets, 850 annotations) · run #12, 2026-06-09 · adapter PR #5 merged_

**Headline score:** 686 / 850 exact (80.7%), 152/153 files processed, 0 spurious.
Precision 0.839 · recall 0.807.

This supersedes the run #9 analysis. Since then the **adapter dotted-name
routing bug is fixed** (PR #5): the ~83 annotations the harness was discarding
— method/nested returns and `self.attr` reads the engine computed correctly —
now score EXACT (603 → 686, +9.8 pts). With that measurement noise removed,
**every remaining miss is genuine engine work.** The gap now sorts cleanly into:
value-sensitive narrowing (§2), genuinely wrong types (§3), bailouts to
`any`/error (§4), and the iterator protocol (§5).

---

## 0. How outcomes are classified

The adapter is **GT-keyed and position-matched**: for each ground-truth location
it looks for an engine binding at the same `(row, col)` and emits a prediction
only there, so **SPURIOUS is structurally always 0**. The three observable
buckets:

- **EXACT (686)** — right place, right type set.
- **TYPE_MISS (132)** — right place, type set differed.
- **LOCATION_MISS (32)** — no prediction landed at the GT key.

| Outcome | Count | Sub-classification |
|---|---:|---|
| TYPE_MISS | 132 | error-only (`any`/`TypeError`/`NameError`/`[]`) 48 · disjoint/wrong 41 · superset/imprecise 31 · partial-overlap 6 · superset+err 6 |
| LOCATION_MISS | 32 | plain-name 21 · `self.attr` 7 · subscript 3 · dotted 1 |

Outcome by kind:

| Kind | EXACT | TYPE_MISS | LOCATION_MISS | Total |
|---|---:|---:|---:|---:|
| parameter | 92 | 3 | 0 | 95 |
| return | 208 | 22 | **0** | 230 |
| variable | 386 | 107 | 32 | 525 |

Note `return` is now **0 LOCATION_MISS** (was 80) — the headline effect of the fix.

---

## 1. ✅ What the adapter fix recovered (was §1's bug, now resolved)

`_lookup_predicted_types` used to test `is_indirect` (any `.` in the GT name)
*before* the `return` branch, so every dotted name — method/nested returns
(`Class.method`, `outer.inner`, `func.dec`) and `self.attr` reads — was routed
into the subscript value-projection path and dropped as LOCATION_MISS, even
though the engine had the right type at the right position. PR #5 resolves
`kind == "return"` first and prefers an exact-name flat binding before
projecting. A/B against the **same engine commit**:

| | before (run #9) | after (run #12) | Δ |
|---|---:|---:|---:|
| EXACT | 603 | 686 | **+83** |
| files sound | 63 | 95 | +32 |
| return LOCATION_MISS | 80 | 0 | −80 |
| `classes` | 55% | 94% | +39 |
| `decorators` | 77% | 98% | +21 |
| `mro` | 44% | 85% | +41 |

Per-annotation transitions (run #9 → #12): **83 LOCATION_MISS → EXACT**,
17 LOCATION_MISS → TYPE_MISS, **0 EXACT regressions**. The 17 are dotted
returns that now resolve but to a wrong/imprecise type — previously hidden as
plumbing, now correctly surfaced as engine type problems (they show up in
§2/§3/§5 below: MRO unions, iterator-protocol `[]`, abstract methods, external
bases). _Autogen saw the same effect: 52,324 → 53,842 (+1,518), 0 regressions._

Everything below is the **genuine engine gap** that remains.

---

## 2. Value-tracking-dependent imprecision (sound union, not narrowed)

TYPE_MISS where the prediction is a **superset** of GT (31) or a strict
**subset** from picking one branch (6 partial-overlap) — the engine is never
*wrong*, it just hasn't done the value-sensitive flow analysis to narrow.
Uniform root cause: **the engine joins over branches / container elements / dict
values / unpack slots / MRO method versions and reports the join (or one
member).**

### 2a. Branch dispatch on a literal value
```python
# returns/multiple_types
def func(x):
    if x > 0: return x          # int
    else:     return "Invalid"  # str
a = func(5)    # GT int   — engine {int,str}
b = func(-5)   # GT str   — engine {int,str}
```
Narrowing `a`/`b` requires tracking that `5 > 0` selects the first branch. Same
shape in `builtins/switch` (`match value: case "case1": return 42 …` —
`func("case1")` GT `int`, engine `{int,str}`). This is the `y = 1 if x>0 else
"one"` example on the **call result**.

### 2b. Dict key → value precision  *(the `d[key1]` / `d[key2]` example)*
```python
# dicts/call
d = {"a": func1, 1: func2, 2: 3}   # func1→str, func2→int
e = d["a"]()   # GT str — engine {TypeError,int,str}
f = d[1]()     # GT int — engine {TypeError,int,str}
#   d['a'] GT callable, d[1] GT callable, d[2] GT int — engine gives all {callable,int}
```
The engine models a dict's value type as the **join of all values** and loses the
per-key mapping. `dicts/param_key` is the same with the key arriving as a
parameter (`func1(key="a"): return d[key]()`).

### 2c. List index precision
```python
# lists/simple
a = [func1, func2, func3]   # int, float, str
c = a[0]()  # GT int   — engine {float,int,str}
d = a[1]()  # GT float — engine {float,int,str}
```
Element type = join of all elements; index identity isn't tracked. `b[0] = func4`
after `b = ["Hello"]` (`b[0]` GT `callable`, engine `{callable,str}`) shows the
join also ignores a later index **reassignment**.

### 2d. Starred-unpack slot identity
```python
# assignments/starred
a, *b, c = func1, func2, func3, func4
e = b[0]()  # GT int (func2)   — engine {float,int}
f = b[1]()  # GT float (func3) — engine {float,int}
```
The starred `b` captures `[func2, func3]`; the engine joins them and can't say
which slot holds which.

### 2e. MRO / override unions (now visible as the 6 partial-overlap + several disjoint)
`mro/two_parents`, `mro/self_assignment`, `inheritance_overriding`: GT unions the
return types of same-named methods up the hierarchy (`{int,str}`); the engine
resolves a single body and returns e.g. `{str}` (`["int","str"]`→`["str"]`).
These flipped LOCATION_MISS→TYPE_MISS with the fix and are now scored honestly.

**Common fixes:** literal/constant propagation through `if`/`match` conditions;
key-sensitive dict modelling (per-constant-key value map, join fallback for
dynamic keys); index-sensitive list/tuple element tracking with reassignment;
positional starred targets; union across the resolved MRO method set.

---

## 3. Genuinely **incorrect** types (disjoint from GT — 41)

Here the engine asserts a single wrong answer, costing soundness/completeness,
not just exactness. This bucket *grew* (32 → 41) because newly-resolved dotted
returns landed on wrong types — a measurement gain, not a regression.

### 3a. Lazy iterators collapsed to `list` (biggest wrong-type cluster)
```python
grouped_data = itertools.groupby(...)  # GT itertools.groupby — engine list
counter      = itertools.count(...)    # GT itertools.count   — engine list
res          = map(...)                # GT map               — engine list
combined     = zip(names, ages)        # GT zip               — engine list
```
`itertools.*`, `map`, `zip` modelled as eager `list`. Knock-on in `builtins/zip`:
`result[0]` GT `tuple`, `result[0][0]` GT `str`, but the engine types the nested
index as `tuple` (the `(str,int)` element structure isn't reconstructed).

### 3b. Generator functions typed as `list`
```python
# generators/yield_next, yield_function
def squares():
    while True: yield n**2
gen = squares()   # GT generator — engine list  (both the return and `gen`)
```
A function containing `yield` should return `generator`; the engine evaluates it
eagerly to `list`.

### 3c. Dropped module / nesting qualifiers on class names
```python
# classes/imported_call        a -> GT 'to_import_call.MyClass'   engine 'MyClass'
# classes/imported_attr_access a -> GT 'to_import.A'              engine 'A'
# exceptions/raise_attr        a -> GT 'A.B'                       engine 'B'
```
The engine reports the bare class name; GT carries the defining-module / outer-
class qualifier. Naming-normalization shaped, but scored as wrong.

### 3d. `*args` typed as `list`, not `tuple`  (`args/multiple` `integers`)

### 3e. Decorator-rebound class identity
```python
# decorators/classes
@my_decorator           # returns NewClass(cls)
class MyClass: ...
a = MyClass()           # GT 'MyClass' — engine 'NewClass'
```
The engine follows the decorator to `NewClass`; GT keeps the syntactic name.
Arguably the engine is *more* faithful — flag as a GT-convention mismatch.

---

## 4. Engine "bailed" — `any` / error / empty (48 error-only)

The engine returned only `any`, `TypeError`, `NameError`, or `[]`. Clusters:

- **External modules → `any`** (`external/*`, `imports/parent_import`,
  `imports/init_func_import`): can't see into `typeevalpy_external_module` /
  some cross-package imports → Top.
- **Dynamic execution → `TypeError`/`NameError`** (`dynamic/eval`, `exec`,
  `compile`): `eval`/`compile` results untyped; `exec`-introduced names unbound.
- **`namedtuple` / `set()` constructors** (`returns/return_types`): `Point(1,2)`
  → `any`; `set([...])` → `[]`. Factory/constructor not modelled.
- **Iterator-protocol returns → `[]`** (`Cls.__next__`, `Cls.__iter__`) — now
  visible as TYPE_MISS (`["int"]`→`[]`, `["Cls"]`→`[]`); see §5.

---

## 5. Generators & the iterator protocol (worst genuine category: 33%)

The biggest real weakness. Distinct from §3b (generator *functions* → list),
this is about **consuming** custom iterables:

```python
# generators/iterable, iter_param, iter_return
class func:
    def __iter__(self): ...
    def __next__(self): ...        # engine: insts=0 — never instantiated
output_list = [i for i in func(...)]
#   output_list[k] GT int — engine TypeError
```
The engine never drives `__iter__`/`__next__`, so:
- comprehension/loop targets over a custom iterable type to `TypeError`/`any`
  (these are most of the 21 plain-name LOCATION_MISS: `i`, `cur`, `result`),
- elements pulled out (`output_list[k]`) become `TypeError`,
- `self.n` / `self.num` read inside the uninstantiated `__next__` are never
  emitted (the 7 residual `self.attr` LOCATION_MISS),
- `Cls.__next__` / `Cls.__iter__` return `[]` (the new TYPE_MISS in §4).

**Fix:** instantiate `__iter__`/`__next__` on iteration and propagate `__next__`'s
return as the loop/comprehension element type. This one capability lifts most of
`generators`, the residual `self.attr`, and several §4 returns together.

---

## 6. Higher-order functions & closures (special focus)

**Now solid after the fix:**
- `lambdas` 34/34, `functions` 37/37, `direct_calls` 24/24 — **all 100%.**
- **Closure capture is correct and now scores EXACT:** `functions/nested`
  `inner` captures `nonlocal x` → `int`; `decorators/return` `dec` captures
  `inner` → `callable`. Their dotted return names (`outer.inner`, `func1.dec`)
  used to be dropped by the adapter bug; they now land.
- Function-valued returns resolve (`direct_calls/return_call`: `func()()` →
  `callable` then `str`).
- **`self`-stored callables** (`classes/self_assignment` `self.smth =
  self.func2`) now type `self.smth -> callable` correctly (was the §1b loss).

**Remaining genuine HOF weakness — dispatch tables of callables:**
`dicts/call`, `dicts/param_key`, `lists/simple`, `assignments/starred` are all
"container of functions, called by key/index." The engine returns the *join* of
all stored callables' return types instead of the selected one (§2b–2d). This is
now the dominant HOF gap, and it's value-tracking, not closures.

---

## 7. Source-position correctness

Still **no evidence the engine emits at wrong coordinates** (0 spurious; every
position checked aligns under the `col+1` convention). With the adapter fix in,
LOCATION_MISS dropped 132 → 32, and the residual 32 are **genuine non-emission**,
not position errors:

- **21 plain-name:** comprehension targets (`lists/comprehension_val`,
  `nested_comprehension`), iterator/loop vars (§5), `*args`/`**kwargs` elements
  (`args/multiple` `x`, `kwargs/multiple` `arg`), dynamic `exec`/`compile`
  locals, `returns/return_types` `set`/comprehension results, and
  `imports/init_import` (fails to translate: `CycleError: import cycle … ['main',
  'nested_init']`).
- **7 `self.attr`:** all in uninstantiated generator `__next__` (§5).
- **3 subscript + 1 dotted:** nested/secondary projections.

"Source position wrong" is not a current failure mode.

---

## 8. Prioritized recommendations (engine — the adapter item is done)

1. **Iterator protocol** (§5): instantiate `__iter__`/`__next__` on iteration;
   propagate element types. Highest leverage — fixes most of `generators` (worst
   real category at 33%), the residual `self.attr`, and several §4 returns.
2. **Value-sensitive narrowing** (§2): literal propagation through `if`/`match`;
   key-sensitive dicts; index-sensitive lists/tuples + reassignment; positional
   starred targets; MRO method-set unions. Clears the superset/partial-overlap
   cluster and the callable-container HOF losses (§6).
3. **Lazy builtins** (§3a/§3b): type `itertools.*`/`map`/`zip` as their iterator
   types and `yield`-functions as `generator` instead of `list`; rebuild `zip`'s
   tuple element structure.
4. **Moderate:** module/outer-class name qualification (§3c); `*args`→`tuple`
   (§3d); `namedtuple`/`set` constructors (§4).
5. **Lower priority:** external-module stubs / dynamic-exec handling (§4) —
   small count, inherently hard, partly out of scope for static analysis.

**Benchmark hygiene:** flag `decorators/classes` (§3e) as a GT-naming-convention
mismatch rather than an engine defect.

---

### Appendix — category rates (run #12, post-fix; worst first)

| Category | Exact/Total | Dominant cause of misses |
|---|---|---|
| external | 2/16 (12%) | §4 external→`any` |
| generators | 23/70 (33%) | §5 iterator protocol; §3b gen→list |
| dynamic | 3/9 (33%) | §4 eval/exec/compile |
| exceptions | 1/2 (50%) | §3c nested-class qualifier |
| builtins | 41/68 (60%) | §3a lazy iterators→list |
| lists | 43/60 (72%) | §2c index precision |
| returns | 35/43 (81%) | §4 namedtuple/set; §3b |
| dicts | 89/107 (83%) | §2b key→value precision |
| imports | 21/25 (84%) | §4 cross-package imports |
| mro | 29/34 (85%) | §2e MRO unions |
| assignments | 76/82 (93%) | §2d starred slots |
| classes | 115/122 (94%) | §5 self.attr in `__next__` |
| args | 41/43 (95%) | §3d `*args`→list |
| kwargs | 21/22 (95%) | §7 `**kwargs` element |
| decorators | 51/52 (98%) | §3e class identity |
| direct_calls | 24/24 (100%) | — |
| functions | 37/37 (100%) | — |
| lambdas | 34/34 (100%) | — |

_Generated from `runs.db` run #12 (micro) and #11 (autogen) against worktree
`loop/nightly-20260609-0826`, adapter PR #5 merged. Replay scripts:
`/tmp/micro_gap_analysis.py`, `/tmp/engine_positions.py`,
`/tmp/quantify_adapter_bug.py`._
