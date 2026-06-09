# Micro Type-Analysis Gap Analysis — Run #9

_Engine worktree `loop/nightly-20260609-0826` · TypeEvalPy micro-benchmark (153 snippets, 850 annotations) · run #9, 2026-06-09_

**Headline score:** 603 / 850 exact (70.9%), 152/153 files processed, 0 spurious.

This report dissects the 247 non-EXACT annotations. The single most important
takeaway: **a large share of the apparent gap is harness measurement plumbing,
not engine capability.** ~83 annotations (≈9.8 points) are types the engine
computes *correctly, at the correct source position*, that the GT-keyed adapter
silently drops. Once those are set aside, the genuine engine gaps fall into a
small number of clean buckets — chief among them **value-sensitive narrowing**
(the engine computes sound unions but doesn't track which branch / index / key /
slot a concrete value flows through) and **lazy iterators / the iterator
protocol** (generators and `itertools`/`map`/`zip` typed as `list`).

---

## 0. How outcomes are classified (so the numbers below are unambiguous)

The harness adapter is **GT-keyed and position-matched** (`archway_adapter.py:`
`ArchwayAnalysisResultAdapter.to_annotations`): for every ground-truth location
it looks for an engine binding at the *exact* `(row, col)` and emits a prediction
only there. Consequences:

- **SPURIOUS is structurally always 0** for this engine — the adapter never
  surfaces predictions at non-GT locations (`# Extra bindings ... are dropped here`).
  So "predicted the wrong place" cannot appear as a spurious row; it can only
  appear as a **LOCATION_MISS** (GT location with no matching prediction).
- Therefore the three observable buckets are:
  - **TYPE_MISS (115)** — engine answered at the right place, type set differed.
  - **LOCATION_MISS (132)** — no prediction landed at the GT coordinate/key.
  - (EXACT 603.)

| Outcome | Count | Sub-classification |
|---|---:|---|
| TYPE_MISS | 115 | superset/imprecise 31 · superset+err 6 · disjoint/wrong 32 · error-only (`any`/`TypeError`/`NameError`) 46 |
| LOCATION_MISS | 132 | dotted returns 80 · `self.attr` 27 · plain-name 21 · subscript 3 · other 1 |

---

## 1. ⚠️ Measurement plumbing: ~83 correct answers dropped by the adapter

This is an adapter (harness) bug, not an engine gap, but it dominates the
LOCATION_MISS count and depresses the reported score by ~9.8 points, so it has to
be understood before anything else.

### 1a. Dotted return names (80 LOCATION_MISS → 63 are correct answers thrown away)

`_lookup_predicted_types` (`archway_adapter.py`) computes `is_indirect` from the
GT name and branches on it **before** checking `loc.kind == "return"`:

```python
base, is_indirect = _split_base(loc.name)   # "MyClass.func1" -> ("MyClass", True)  ← "." seen as attr access
...
if is_indirect:                              # TRUE for every Class.method / outer.inner / func.dec
    ... _value_element(elt) ...              # callable element -> None -> dropped -> LOCATION_MISS
if loc.kind == "return":                     # dead code for any qualified function name
    returns = _callable_returns_for(...)
```

TypeEvalPy names **every method / nested-function return** with a dotted path
(`MyClass.func1`, `outer.inner`, `func1.dec`, `my_decorator.NewClass.my_method`).
`_split_base` splits on `.`, flags it as an attribute access, and the
return-resolution branch never runs. The engine *does* emit the right thing —
verified directly against the live server:

| Snippet | GT return | Engine `def@pos` → resolved ret | Scored |
|---|---|---|---|
| `classes/return_call` `MyClass.func1` | `callable` | `def@L8C8`→col9 ✓, ret `callable` | LOCATION_MISS |
| `classes/nested_call` `MyClass.func.nested` | `str` | `def@L4C12`→col13 ✓, ret `str` | LOCATION_MISS |
| `decorators/return` `func1.dec` | `callable` | `def@L5C8`→col9 ✓, ret `callable` | LOCATION_MISS |
| `functions/nested` `outer.inner` | `int` | `def@L7C8`→col9 ✓, ret `int` | LOCATION_MISS |
| `direct_calls/return_call` `…nested_return_func` | `str` | `def@L5C8`→col9 ✓, ret `str` | LOCATION_MISS |

**Replaying all 80 against the live engine with the un-bugged return logic
(match fn by def-position, union its instantiations' `ret` elements):**

- **63 → would be EXACT** (correct type, correct position).
- 17 → would still be TYPE_MISS — these *are* genuine engine issues:
  - MRO / override unions (`mro/two_parents` `B.func` GT `{int,str}`, engine
    `str`; `inheritance_overriding` `MyClass.func` GT `{int,str}`, engine `str`) —
    GT unions all method versions across the hierarchy; the engine resolves the
    one most-derived body. *(value-sensitive; see §2.)*
  - Iterator-protocol methods (`Cls.__next__`, `Cls.__iter__`) return `[]` —
    uninstantiated (`insts=0`); the engine never drives the protocol. *(see §5.)*
  - External base classes (`external/cls_parent` `A.fn` → `any`). *(see §4.)*
  - `classes/abstract_class` `Shape.area` → `[]` (abstract, no instantiation).

### 1b. `self.attr` reads (27 LOCATION_MISS → 20 are correct answers thrown away)

Same root cause. `_split_base("self.smth")` → `("self", True)` → `is_indirect`
branch → `_value_element(callable)` returns `None` (it only projects
`dict`/`list`/`tuple` value/element types, not instance attributes) → dropped.

The engine emits the attribute as a *single flat binding* named `self.smth` at the
store site, with the correct type and position:

```
classes/self_assignment   GT:  self.smth @L6C9 -> ['callable']
                       engine:  local self.smth @L6C8 (→col9 ✓) -> callable
```

**Replaying all 27 by direct element-flatten: 20 → would be EXACT.** The 7
residual misses are all `self.n` / `self.num` inside generator/iterator classes
where the read happens in an uninstantiated `__next__` (§5).

### 1c. Net impact and the fix

| | Count | If adapter fixed |
|---|---:|---|
| Dotted returns | 80 | +63 EXACT |
| `self.attr` | 27 | +20 EXACT |
| **Total** | **107** | **+83 EXACT → 686/850 ≈ 80.7%** |

**Fix** (harness side, `archway_adapter.py:_lookup_predicted_types`): resolve
`loc.kind == "return"` *before* the `is_indirect` branch, and for variable reads
treat a binding whose literal name equals the dotted GT name as a direct hit
(flatten its element) rather than projecting through `_value_element`. Reserve the
`is_indirect` value-projection path for genuine subscript/attribute GT entries
(`x[0]`, `d['k']`) that don't have a same-named binding.

> **Caveat for every number below:** because of §1, the *reported* category rates
> understate the engine on `classes` (51 LOCATION_MISS, mostly dotted returns +
> `self.attr`), `decorators` (11), and `mro` (19). The engine's real weak spots
> are in §2–§5.

---

## 2. Value-tracking-dependent imprecision (sound union, not narrowed)

These are TYPE_MISS where the prediction is a **strict superset** of GT —
the engine is never *wrong* (the right type is always in the set), it just hasn't
done the value-sensitive flow analysis needed to narrow. This is exactly the class
of problem flagged in the request. 31 superset + 6 superset+err + ~6 of the MRO
union cases from §1a. Root cause is uniform: **the engine joins over branches /
container elements / dict values / unpack slots and reports the join.**

### 2a. Branch dispatch on a literal value
```python
# returns/multiple_types
def func(x):
    if x > 0: return x          # int
    else:     return "Invalid"  # str
a = func(5)    # GT int   — engine {int,str}
b = func(-5)   # GT str   — engine {int,str}
```
The function's return type *is* `{int,str}`; narrowing `a`/`b` requires tracking
that `5 > 0` selects the first branch. Identical shape in `builtins/switch`
(`match value: case "case1": return 42 ...` — `func("case1")` GT `int`, engine
`{int,str}` for all three calls). This is the report's `y = 1 if x>0 else "one"`
example, manifesting on the **call result**.

### 2b. Dict key → value precision  *(the request's `d[key1]` / `d[key2]` example)*
```python
# dicts/call
d = {"a": func1, 1: func2, 2: 3}   # func1→str, func2→int
e = d["a"]()   # GT str — engine {TypeError,int,str}
f = d[1]()     # GT int — engine {TypeError,int,str}
#   d['a'] GT callable, d[1] GT callable, d[2] GT int
#   engine gives ALL of them {callable,int}  ← value type = join of every dict value
```
The engine models a dict's value type as the **join of all values** and loses the
per-key mapping. `dicts/param_key` is the same with the key arriving as a function
parameter (`func1(key="a"): return d[key]()`).

### 2c. List index precision
```python
# lists/simple
a = [func1, func2, func3]   # int, float, str returns
c = a[0]()  # GT int   — engine {float,int,str}
d = a[1]()  # GT float — engine {float,int,str}
e = a[2]()  # GT str   — engine {float,int,str}
```
List element type = join of all elements; positional/index identity isn't tracked.
`b[0] = func4` after `b = ["Hello"]` (`lists/simple` `b[0]` GT `callable`, engine
`{callable,str}`) shows the same join also fails to honour a later index
**reassignment**.

### 2d. Starred-unpack slot identity
```python
# assignments/starred
a, *b, c = func1, func2, func3, func4
e = b[0]()  # GT int (func2)   — engine {float,int}
f = b[1]()  # GT float (func3) — engine {float,int}
```
The starred middle `b` captures `[func2, func3]`; the engine joins them and can't
say which slot holds which.

### 2e. MRO / override unions (overlaps §1a)
`mro/two_parents`, `inheritance_overriding`: GT unions the return types of all
same-named methods up the hierarchy (`{int,str}`); the engine resolves a single
body. Whether GT or engine is "more correct" is debatable, but per the benchmark
these score as misses and they're value/dispatch-sensitive.

**Common fixes:** literal/constant propagation through `if`/`match` conditions;
key-sensitive dict modelling (keep a per-constant-key value map, fall back to join
for dynamic keys); index-sensitive list/tuple element tracking with support for
reassignment; positional modelling of starred targets.

---

## 3. Genuinely **incorrect** types (disjoint from GT — not just imprecise)

32 disjoint + much of the 46 error-only. Here the engine asserts a single wrong
answer, which also costs *soundness* and *completeness*, not just exactness.

### 3a. Lazy iterators collapsed to `list` (biggest wrong-type cluster)
```python
# builtins/itertools, builtins/map, builtins/zip
grouped_data = itertools.groupby(...)  # GT itertools.groupby — engine list
counter      = itertools.count(...)    # GT itertools.count   — engine list
res          = map(...)                # GT map               — engine list
combined     = zip(names, ages)        # GT zip               — engine list
```
`itertools.*`, `map`, `zip` are modelled as eager `list`. GT wants the specific
lazy iterator type. Knock-on: in `builtins/zip`, `result = list(combined)` gives
`result[0]` GT `tuple` and `result[0][0]` GT `str`, but the engine types the
nested index as `tuple` (the zipped tuple's *heterogeneous element structure*
`(str,int)` isn't reconstructed).

### 3b. Generator functions typed as `list`
```python
# generators/yield_next, generators/yield_function
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
The engine reports the bare class name; GT carries the **defining-module / outer-
class qualifier**. Plumbing-ish (naming normalization), but currently scored as
wrong.

### 3d. `*args` typed as `list`, not `tuple`
```python
# args/multiple
def my_sum(a, b, *integers):   # GT integers: tuple — engine list
```

### 3e. Decorator-rebound class identity
```python
# decorators/classes
@my_decorator           # returns NewClass(cls)
class MyClass: ...
a = MyClass()           # GT 'MyClass' — engine 'NewClass'
```
The engine follows the decorator to `NewClass`; GT keeps the syntactic name
`MyClass`. Arguably the engine is *more* faithful here, but it's a miss against the
benchmark — flag as a GT-convention mismatch rather than an engine defect.

---

## 4. Engine "bailed" — `any` / error types (46 error-only TYPE_MISS)

The engine returned only `any`, `TypeError`, or `NameError` — it gave up rather
than guessed wrong. Clusters:

- **External modules → `any`** (`external/*`, `imports/parent_import`,
  `imports/init_func_import`): the engine can't see into `typeevalpy_external_module`
  or resolve some cross-package imports, so attribute/return types degrade to Top.
- **Dynamic execution → `TypeError`/`NameError`** (`dynamic/eval`, `exec`,
  `compile`): `eval(...)`/`compile(...)` results are untyped (`TypeError`), and
  names introduced via `exec` are unbound at analysis time (`NameError`).
- **`namedtuple` / `set()` constructors** (`returns/return_types`): `func3` returns
  `Point(1,2)` → `any`; `func4` returns `set([...])` → `[]` (empty). The
  `namedtuple` factory and `set` literal/constructor aren't modelled.
- **Iterator-protocol pulls → `TypeError`** — see §5.

---

## 5. Generators & the iterator protocol (the worst genuine category: 26%)

After removing the §1 plumbing losses, `generators` is the weakest real area.
Distinct from §3b (generator *functions* → list), this is about **consuming**
custom iterables:

```python
# generators/iterable, iter_param, iter_return
class func:
    def __iter__(self): ...
    def __next__(self): ...        # engine: insts=0  (never instantiated)
output_list = [i for i in func(...)]
#   output_list[k] GT int — engine TypeError
```
The engine does not drive `__iter__`/`__next__`, so:
- comprehension/loop targets over a custom iterable type to `TypeError` or `any`
  (`<listcomp>` `local i -> TypeError`),
- elements pulled out (`output_list[k]`) become `TypeError`,
- `self.n` / `self.num` read inside the uninstantiated `__next__` are never emitted
  (the 7 residual `self.attr` misses from §1b),
- `Cls.__next__` / `Cls.__iter__` return types are `[]`.

**Fix:** model the iterator protocol — instantiate `__iter__`/`__next__` when a
value is iterated, and propagate `__next__`'s return as the loop/comprehension
element type. This single capability would lift most of `generators` and several
residual §1 cases together.

---

## 6. Higher-order functions & closures (special focus)

**What already works well:**
- `lambdas` — **34/34 EXACT (100%).**
- **Closure capture tracking is correct.** `functions/nested`: `inner` captures
  `nonlocal x` and the engine resolves `captu x -> int` and `inner`'s return
  `int`; `decorators/return`: `dec` captures `inner` (`captu inner -> callable`).
  These are computed right — they only *appear* as misses because their return GT
  names are dotted (`outer.inner`, `func1.dec`) and hit the §1a adapter bug.
- Returning functions as values is resolved (`direct_calls/return_call`:
  `func()()` → `func` returns `return_func` (callable) → `nested_return_func`
  (str); module bindings `a -> callable`, `b -> str` are EXACT).

**Where HOF/closures genuinely break:**
- **Dispatch tables of callables** lose key/index→value identity (§2b/2c):
  `dicts/call`, `dicts/param_key`, `lists/simple`, `assignments/starred` are all
  HOF patterns (a container of functions, called by key/index). The engine returns
  the *join* of all stored callables' return types instead of the selected one.
  This is the dominant real HOF weakness.
- **Decorator-as-factory class identity** (§3e, `decorators/classes`).
- **`self`-stored callables** (`classes/self_assignment` `self.smth = self.func2`;
  `mro/self_assignment`): the engine correctly types `self.smth -> callable`, but
  it's dropped by §1b; the *call* `self.smth()` resolving back to `func2`'s `str`
  return does land correctly where the result is a plain name.

Net: the engine's HOF/closure *core* (capture, function-valued returns, calling
returned functions) is solid; the losses are (1) the adapter dotted-name bug
masking method/closure returns, and (2) value-identity tracking through
callable containers.

---

## 7. Source-position correctness

With 0 spurious, there is **no evidence of the engine emitting types at wrong
coordinates.** Every position we checked lines up under the adapter's
0-indexed→1-indexed `col+1` convention (`def@L8C8`→GT col 9, `self.smth@L6C8`→GT
col 9, etc.). The 132 LOCATION_MISS decompose as:

- **107 adapter-routing losses** (§1) — engine has the binding at the right place,
  adapter drops it.
- **~25 genuine non-emission** — the engine truly produces nothing at that key:
  comprehension targets (`lists/comprehension_val`, `nested_comprehension` `a`,`b`),
  `*args`/`**kwargs` element vars (`args/multiple` `x`, `kwargs/multiple` `arg`),
  iterator-protocol locals (§5), dynamic `exec`/`compile` locals, and the
  `imports/init_import` snippet which fails to translate entirely (`CycleError:
  import cycle detected among modules: ['main','nested_init']`).

So "source position wrong" is effectively **not** a current failure mode for the
engine; the position-shaped symptom is really the §1 adapter representation
mismatch (the engine names attributes/methods with flat dotted keys; the adapter
expects to *project* through a base binding).

---

## 8. Prioritized recommendations

**Harness (cheap, ~+10 pts of *reported* score, no engine change):**
1. Fix `_lookup_predicted_types` ordering so `return` resolves before
   `is_indirect`, and so a literal dotted binding name is a direct hit. Recovers
   ~63 dotted returns + ~20 `self.attr` = **~83 annotations (70.9% → ~80.7%)**.
   _This should be done first so subsequent engine work is measured honestly._

**Engine — highest leverage (genuine capability):**
2. **Iterator protocol** (§5): instantiate `__iter__`/`__next__` on iteration;
   propagate element types. Fixes most of `generators` (worst real category) +
   residual `self.attr` + several §1a residuals together.
3. **Value-sensitive narrowing** (§2): literal propagation through `if`/`match`;
   key-sensitive dicts; index-sensitive lists/tuples + reassignment; positional
   starred targets. Clears the superset cluster and the callable-container HOF
   losses.
4. **Lazy builtins** (§3a/§3b): type `itertools.*`/`map`/`zip` as their iterator
   types and `yield`-functions as `generator` (stop collapsing to `list`); rebuild
   `zip`'s tuple element structure.

**Engine — moderate:**
5. Module/outer-class **name qualification** (§3c); `*args`→`tuple` (§3d);
   `namedtuple`/`set` constructors (§4).
6. **External module** stubs / dynamic-exec handling (§4) — lower priority
   (small count, inherently hard, partly out of scope for static analysis).

**Benchmark hygiene:**
7. Flag `decorators/classes` (§3e) as a GT-naming-convention mismatch rather than
   an engine defect.

---

### Appendix — category rates (as reported, before §1 correction)

| Category | Exact/Total | Dominant cause of misses |
|---|---|---|
| external | 2/16 (12%) | §4 external→`any` |
| generators | 18/70 (26%) | §5 iterator protocol; §3b gen→list |
| dynamic | 3/9 (33%) | §4 eval/exec/compile |
| mro | 15/34 (44%) | §1a dotted returns + §2e unions |
| classes | 67/122 (55%) | §1 adapter (dotted returns + `self.attr`) |
| builtins | 41/68 (60%) | §3a lazy iterators→list |
| lists | 43/60 (72%) | §2c index precision |
| decorators | 40/52 (77%) | §1a dotted returns |
| dicts | 89/107 (83%) | §2b key→value precision |
| lambdas | 34/34 (100%) | — |

_Generated from `runs.db` run #9 + live-engine replay against worktree
`loop/nightly-20260609-0826`. Replay scripts: `/tmp/micro_gap_analysis.py`,
`/tmp/engine_positions.py`, `/tmp/quantify_adapter_bug.py`._
