# Run #36 — Micro-benchmark misses analysis

_For the analysis + translation agents working on Archway._
_Run #36 ran from the `Archway-loop` worktree at HEAD `41573dd types: distribute populates summands (catches up to fresh-UID encoding)`, micro benchmark, 2026-06-04._

## Headline

| Outcome | Count | Share |
|---|---:|---:|
| **EXACT** | **559** | **65.8%** |
| LOCATION_MISS | 160 | 18.8% |
| TYPE_MISS | 131 | 15.4% |
| TRANSLATION_ERROR | 0 | 0% |
| **Total annotations** | **850** | |

Files processed: **150/153**. Sound: **57**. Complete: **98**.

The biggest single bucket is now **LOCATION_MISS (160)** — bindings the adapter couldn't locate at the GT position. That's 30 cases more than TYPE_MISS, so the next big push isn't in type precision but in surfacing bindings that the analysis already produces under names the GT expects.

## Where the misses live

### LOCATION_MISS (160 total)

| Name shape | Count | What |
|---|---:|---|
| `Class.method` return entries | 80 | GT says `return … function: "Shape.area"`; adapter looks up `"Shape.area"` but the analysis surfaces `"area"` only |
| `self.X` instance-attr writes | 27 | GT says `variable: "self.width"`; analysis records the write but adapter doesn't index it under the `self.X` name |
| Plain (no dot, no `[]`) | 45 | Names that should be findable directly — probably analysis-side bindings missing |
| Deep `A.B.method` | 3 | Nested classes |
| Subscript `b[0]` / `d['b']` | 7 | Star-unpack and dict subscript |

By kind:

| Kind | EXACT | TYPE_MISS | LOCATION_MISS | Total |
|---|---:|---:|---:|---:|
| return | 140 | 10 | **80** | 230 |
| variable | 346 | 115 | 64 | 525 |
| parameter | 73 | 6 | 16 | 95 |

`return` LOCATION_MISS is **almost entirely** the `Class.method` projection gap — 80 of 80.

### TYPE_MISS (131 total)

| count | kind | expected → predicted | likely root |
|---:|---|---|---|
| 20 | variable | `[int] → [TypeError]` | translation gap on generators / unpacking |
| 36 (all kinds) | * | `[T] → [TypeError]` | same translation bucket, broader |
| 35 (all kinds) | * | `[T] → [any]` | analysis over-widening to top |
| 12 (all kinds) | * | overgeneralization `[X] → [int,str]` | path-insensitive narrowing (known) |
| 7 | variable | `[str] → [int, str]` | switch/dict-dispatch widening |
| 3 | parameter | `[int] → [TypeError]` | call-arg propagation |

### Per-category accuracy (worst first)

| Category | EXACT | Total | Rate | Main miss type |
|---|---:|---:|---:|---|
| external | 2 | 16 | 12.5% | pip imports unmodelled (expected) |
| generators | 13 | 70 | 18.6% | iterator/comprehension typing |
| dynamic | 3 | 9 | 33.3% | exec/compile (out of scope) |
| mro | 13 | 34 | 38.2% | mostly `Class.method` LOCATION_MISS |
| classes | 60 | 122 | 49.2% | `Class.method` returns (51 LOC_MISS) |
| exceptions | 1 | 2 | 50.0% | tiny |
| builtins | 35 | 68 | 51.5% | reduce/groupby/map returning `any` |
| lists | 37 | 60 | 61.7% | path-insensitive widening |
| imports | 17 | 25 | 68.0% | most stdlib imports work; some return-type cascades |
| returns | 31 | 43 | 72.1% | mostly fine |
| decorators | 40 | 52 | 76.9% | mostly fine; 11 LOC_MISS on decorated method names |
| dicts | 86 | 107 | 80.4% | |
| assignments | 70 | 82 | 85.4% | chained assignment LHS still rough |
| functions | 32 | 37 | 86.5% | |
| args | 41 | 43 | 95.3% | |
| kwargs | 21 | 22 | 95.5% | |
| direct_calls | 23 | 24 | 95.8% | |
| **lambdas** | **34** | **34** | **100.0%** | clean sweep |

## Concrete examples

### 1. Class.method return entries — 80 LOCATION_MISS

GT pattern: `{"function": "MyClass.func", "line_number": N, "col_offset": C, "type": [...]}`. Adapter currently looks up just `"func"` (or fails on the qualified name).

```py
# classes/assigned_call  L3 — GT entry is `function: "MyClass.func"`, exp ["str"]
class MyClass:
    def func(self):
        return "Hello from func"
```

```py
# mro/basic  L5 — GT entry `function: "A.func"`, exp ["int"]
class A:
    def func(self):
        return 42
```

```py
# classes/base_class_attr  L7 — GT entry `function: "A.B.bfunc"`, exp ["int"]
class A:
    class B:
        def bfunc(self):
            return 42
```

**Whose work:** primarily an **analysis-side** projection question (does the FinalizedAnalysis surface methods under `<class qualname>.<method>`?) and/or an **adapter** question (should we resolve `Class.method` by walking class → body fn-id → that fn's return)?

### 2. `self.X` instance-attr writes — 27 LOCATION_MISS

GT pattern: `{"variable": "self.width", "line_number": N, "col_offset": C, "type": ["int"]}`.

```py
# classes/abstract_class  L12
class Rectangle(Shape):
    def __init__(self, width, height):
        self.width = width    # GT here: variable "self.width", exp ["int"]
        self.height = height
```

```py
# classes/nested_class_calls  L9
class B:
    def __init__(self, c):
        self.c = c            # GT: variable "self.c", exp ["C"]
```

**Whose work:** analysis-side — instance-attribute writes need a binding event keyed at the `self.X` source position (with the RHS's type as the element), surfaced in the `FinalizedAnalysis` projection. Adapter likely needs a small follow-up to index these by `self.X` after the analysis exposes them.

### 3. Plain LOCATION_MISS (45 cases) — bindings missing under expected names

These are NOT subscript or attribute — names the GT expects directly.

```py
# assignments/chained  L12 — GT for variable "b" at L12 C5, exp ["callable"]
a = b = func1
```

Multi-target chained assignment: only `a` is surfaced, `b` (the middle target) is missing. **Analysis side** — should surface per-target binding events for chained assignment.

```py
# assignments/walrus  L6 C22 — GT for variable "word", exp ["str"]
def count_words(string):
    words = string.split()
    word_count = 0
    while words and (word := words.pop()):  # ← walrus target
        ...
```

Walrus operator target not bound. **Analysis side.**

```py
# assignments/starred  L18 C5 — GT for variable "b", exp ["list"]
a, *b, c = func1, func2, func3, func4
```

Starred unpack target. **Analysis side.**

```py
# assignments/generators  L4 C21 — GT for variable "i", exp ["int"]
x, y, z = (i**2 for i in range(1, 4))
```

Generator-comprehension iteration variable. **Analysis side.**

```py
# builtins/functools  L5 C14 — GT for parameter "x", exp ["int"]
def multiply(x, y):
    return x * y

result = reduce(multiply, [1, 2, 3])
```

Parameter `x` not bound. Could be that `multiply` is never called directly by user code (only passed to `reduce`), so the analysis never instantiates it from a call site. **Analysis side** — either model `reduce`'s callable arg invocation, or the param is fundamentally unhinted-untraceable here.

### 4. Subscript LOCATION_MISS (7) — chained-tuple star unpack

```py
# assignments/starred  L18 C5 — GT entries variable "b[0]" and "b[1]"
a, *b, c = func1, func2, func3, func4
```

Star-unpack indexed access. **Analysis side** — the elements of `b` need to be bindable as `b[0]`, `b[1]` post-unpack.

```py
# dicts/add_key  L10 — GT variable "d['b']", exp ["callable"]
d = {}
d["b"] = func   # ← string-keyed dict write
```

String-keyed dict subscript-write isn't projected as `d['b']`. **Analysis side / adapter** — possibly model literal-keyed dict slots.

### 5. `[int] → [TypeError]` — 36 cases, biggest TYPE_MISS bucket

```py
# assignments/generators  L4 — GT variable "x" exp ["int"], pred ["TypeError"]
x, y, z = (i**2 for i in range(1, 4))
```

Generator-comprehension destructuring → `TypeError`. **Translation-side** — the destructuring on top of a generator expression probably hits a translation gap (likely `i**2` or the genexpr iteration).

```py
# builtins/map  L6 — GT variable "res" exp ["map"], pred ["TypeError"]
def func(x): return x

res = map(func, [1, "Hello", 3.0])
x, y, z = res
```

`map(...)` produces `TypeError`. **Translation gap** — `map()` call modeling.

```py
# generators/iter_param  L5 — `output_list = [i for i in c]` produces TypeError
def func(c):
    output_list = [i for i in c]
    return output_list
```

List comprehension over an unhinted parameter → TypeError. **Translation gap** on the comprehension.

### 6. `[T] → [any]` — 35 cases, overwide top

```py
# builtins/functools  L10 — exp ["int"], pred ["any"]
numbers = [1, 2]
product = reduce(multiply, numbers)
```

**Analysis-side** — `functools.reduce` isn't modelled. Returning `any` instead of inferring `int` from the lambda body's return.

```py
# builtins/itertools  L13 — exp ["itertools.groupby"], pred ["any"]
grouped_data = itertools.groupby(sorted_data, key=lambda x: x["city"])
```

**Stdlib modeling** — `itertools.groupby` returns `groupby` (which the GT spells `itertools.groupby`). Could either model the stdlib or accept lenient mapping.

```py
# external/attribute  L7 — pred ["any"]
a = Cls()
b = a.fun()   # ← method on external pip-installed class
```

External pip imports — known gap, expected to stay at `any`.

### 7. Overgeneralization `[X] → [int, str]` — 12 cases

```py
# builtins/switch  L12 — exp ["int"], pred ["int", "str"]
def func(case):
    switch = {"case1": 1, "case2": "two", "case3": "three"}
    return switch[case]

a = func("case1")  # GT: ["int"]
b = func("case2")  # GT: ["str"]
c = func("case3")  # GT: ["str"]
```

Path-insensitive dict-dispatch: analysis returns the union of all dict values for every call. Known limitation — would require value-flow-sensitive dict modeling or per-call-site narrowing. The user has previously flagged this kind of case as "firmly within abstract-interpretation territory."

## Recommended ordering for the agents

Roughly by impact (gain estimate is best-case if all sub-cases land):

1. **`Class.method` surfacing — analysis + adapter, est. +80 cases.** Make methods bindable under their qualified class name in `FinalizedAnalysis` (or have the adapter resolve them by walking class → method body). All 80 return LOCATION_MISS for class methods clear in one shot.

2. **`self.X` instance-attr writes — analysis, est. +25 cases.** Emit binding events at the `self.X` source position so the adapter can find them.

3. **Generator/comprehension translation TypeErrors — translation, est. +15 cases.** `[i**2 for i in range(...)]` and friends. Currently produces TypeError on multiple GT entries per snippet.

4. **`map(...)` and `reduce(...)` stdlib modeling — analysis, est. +10 cases.** Both currently produce TypeError or `any`. Worth modelling the call shape for these two specifically.

5. **Chained `a = b = expr` and walrus `(x := expr)` LHS bindings — analysis, est. +10 cases.** Per-target events for chained assignment; bound-name event for walrus target.

6. **Star-unpack indexed access (`*b` then `b[0]`/`b[1]`) — analysis, est. +5 cases.** Make unpacked-star elements indexable.

7. **`itertools.groupby` / iterator-element types — analysis, possibly out of scope.** ~5 cases.

8. **External pip imports — known gap, won't fix.** ~14 cases stay.

9. **Path-insensitive dict-dispatch — known abstract-interpretation gap.** ~12 cases stay.

Expected ceiling if 1–6 land cleanly: **~700/850 (82%)** on micro, with the remainder being scoped-out (external/dynamic) or known abstract-interpretation limitations.

## Quick links

- Per-run detail report: `archway_report_run36.md`
- Progress history: `archway_progress.md`
- Engine + adapter source: `src/archway_benchmarks/engines/archway.py`, `src/archway_benchmarks/benchmarks/archway_adapter.py`
- Previous miss analyses: `docs/run20_type_miss_analysis.md`, `docs/run24_type_miss_analysis.md`
