# Run #44 — Micro-benchmark misses analysis

_State of Archway on TypeEvalPy's micro-benchmark, with each remaining miss classified by what kind of work would close it._

_Run from the `Archway-loop` worktree, micro = 153 snippets / 850 annotations, 2026-06-05._

## Headline

| Outcome | Count | Share |
|---|---:|---:|
| **EXACT** | **599** | **70.5%** |
| LOCATION_MISS | 138 | 16.2% |
| TYPE_MISS | 113 | 13.3% |
| TRANSLATION_ERROR | 0 | 0% |

Files processed **152/153**, sound **62**, complete **107**.

For external context: HeaderGen scores **591/850 (69.5%)** on this same benchmark, Jedi 476, Sonar 241, Scalpel 183, and Astral's `ty` (with our reveal-type runner) 411. Archway is now **+8 ahead of HeaderGen** at run #44 and the remaining 251 misses sort neatly into three buckets — surfacing gaps, translation gaps, and cases that genuinely require value-flow reasoning beyond pure type inference.

## Where Archway is strong

Categories at ≥90% accuracy — these features work well and don't need targeted attention right now:

| Category | EXACT | Total | Rate | What's working |
|---|---:|---:|---:|---|
| lambdas | 34 | 34 | **100.0%** | Lambdas as values, params, returns; lambda composition |
| direct_calls | 23 | 24 | 95.8% | Direct function calls, return-type propagation |
| kwargs | 21 | 22 | 95.5% | Keyword arguments, default values |
| args | 41 | 43 | 95.3% | Positional args, default args, variadics largely OK |
| functions | 35 | 37 | 94.6% | First-class function passing |
| assignments | 76 | 82 | 92.7% | Simple, tuple, augmented, generators (most) |

This is the foundation. Function calls + basic value propagation + lambdas are all clean.

## Mid-tier categories (70–90%) — TYPE_MISS dominates

| Category | EXACT | Total | Rate | Main miss shape |
|---|---:|---:|---:|---|
| imports | 21 | 25 | 84.0% | A handful of multi-module cascade misses |
| dicts | 86 | 107 | 80.4% | Path-insensitive dict-value widening; subscript-of-subscript |
| decorators | 40 | 52 | 76.9% | 11 LOCATION_MISS on decorated method names |
| returns | 33 | 43 | 76.7% | Tuple-return destructuring |
| lists | 43 | 60 | 71.7% | Path-insensitive list-element widening (see §"out-of-scope" below) |

## Lower-tier categories (<70%) — split between fixable and fundamental

| Category | EXACT | Total | Rate | Primary cause |
|---|---:|---:|---:|---|
| builtins | 41 | 68 | 60.3% | Translation TypeErrors on comprehensions + stdlib modeling gaps |
| classes | 67 | 122 | 54.9% | 51 LOCATION_MISS — `ClassName.method` & `self.X` not surfaced |
| exceptions | 1 | 2 | 50.0% | Sample size 2 |
| mro | 15 | 34 | 44.1% | Same `ClassName.method` pattern (19/19 misses) |
| dynamic | 3 | 9 | 33.3% | `exec`/`compile` — fundamentally out of scope |
| generators | 17 | 70 | 24.3% | Comprehension translation + generator return |
| external | 2 | 16 | 12.5% | External pip imports — out of scope by decision |

## Categorising the remaining 251 misses

The next section sorts every miss into one of four buckets:

| Bucket | Cases | What it is | Whose work |
|---|---:|---|---|
| A — Surfacing gaps | ~108 | Analysis records a binding, just not under the name the GT uses | analysis + adapter |
| B — Translation gaps | ~30 | Specific Python constructs translate to `TypeError` instead of binding | translation |
| C — Stdlib modeling | ~15 | `functools.reduce`, `itertools.{groupby, chain, count, ...}`, `map` | analysis (small) |
| D — Beyond pure type inference | ~58 | Requires value-flow / aliasing / dynamic execution to resolve correctly | abstract interpretation, or accepted gap |
| **Total** | **~211** | (the remaining ~40 are misc small) | |

### Bucket A — Surfacing gaps (108 cases) — biggest single push

**A.1 — `ClassName.method` not surfaced as return-fn name (81 cases).** GT expects `"function": "Shape.area"`; current FinalizedAnalysis surfaces methods as bare `area`. The adapter can't disambiguate which class's method to look up.

```py
# classes/assigned_call  L3 — GT { function: "MyClass.func", exp: ["str"] }
class MyClass:
    def func(self):
        return "Hello from func"
```

```py
# mro/basic  L5 — GT { function: "A.func", exp: ["int"] }
class A:
    def func(self):
        return 42
```

```py
# classes/base_class_attr  L7 — GT { function: "A.B.bfunc", exp: ["int"] }
class A:
    class B:
        def bfunc(self):
            return 42
```

Fix: emit functions under their **enclosing-class qualified name** in `FinalizedAnalysis.functions[].name`, OR have the adapter walk the class → method body fn-id resolution. Whichever side does it, this clears 81 cases. Mostly hits `classes/*` and `mro/*`.

**A.2 — `self.X` instance-attr writes (27 cases).** GT expects `"variable": "self.width"`; analysis doesn't emit a binding event at the `self.X` source position.

```py
# classes/abstract_class  L12 — GT { variable: "self.width", exp: ["int"] }
class Rectangle(Shape):
    def __init__(self, width, height):
        self.width = width    # ← no binding event surfaced under `self.width`
        self.height = height
```

```py
# classes/nested_class_calls  L9 — GT { variable: "self.c", exp: ["C"] }
class B:
    def __init__(self, c):
        self.c = c
```

Fix: emit a binding event at the `self.attr` source position in `module.bindings` (or in the instantiation's locals) with the element being the RHS's lattice type.

### Bucket B — Translation gaps (30 cases)

**B.1 — List comprehensions and generator expressions (~15 cases).** Almost every comprehension currently translates to a `TypeError`.

```py
# generators/iter_param  L5 — exp ["int"], pred ["TypeError"] for output_list[0..2]
def func(c):
    output_list = [i for i in c]   # ← comprehension hits translation gap
    return output_list

a = func([1, 2, 3])
```

```py
# assignments/generators  L4 — exp ["int"] for x, y, z; pred ["TypeError"]
x, y, z = (i**2 for i in range(1, 4))
```

The iter-variable inside the comprehension (`i`) is also lost — that's a LOCATION_MISS in generators/ (31 LOCATION_MISS there).

**B.2 — `map(...)` call shape (~6 cases).**

```py
# builtins/map  L6 — exp ["map"], pred ["TypeError"] for res
def func(x): return x
res = map(func, [1, "Hello", 3.0])    # ← map() translation gap
x, y, z = res                          # ← then star-unpack of map result
```

**B.3 — Chained / walrus / star-unpack LHS (~5 cases).**

```py
# assignments/chained  L12 — GT { variable: "b", exp: ["callable"] }, pred null
a = b = func1                          # ← middle target `b` not emitted

# assignments/walrus  L6 — GT { variable: "word", exp: ["str"] }, pred null
while words and (word := words.pop()): ...    # ← walrus target not bound

# assignments/starred  L18 — GT { variable: "b", exp: ["list"] }, pred null
a, *b, c = func1, func2, func3, func4         # ← starred target not bound
```

**B.4 — Generator function `def f(): yield ...` return-type form (2 cases).** GT expects `["generator"]`, analysis returns `["list"]`.

```py
# generators/yield_function  L8 — GT { function: "func1", exp: ["generator"] }
def func1(n):
    num = 0
    while num < n:
        yield num
        num += 1
```

### Bucket C — Stdlib modeling gaps (15 cases)

Cases where the result of a stdlib call lands as `["any"]` or the wrong concrete type, because the call shape isn't in the analysis's stdlib stub model.

```py
# builtins/functools  L10 — exp ["int"], pred ["any"]
numbers = [1, 2]
product = reduce(multiply, numbers)      # ← reduce(fn, list[T]) -> T not modeled
```

```py
# builtins/itertools  L13 — exp ["itertools.groupby"], pred ["list"]
grouped = itertools.groupby(sorted_data, key=lambda x: x["city"])

# L15 — exp ["str"] for city, ["itertools._grouper"] for group, pred ["any"]
for city, group in grouped:
    print(city, list(group))
```

Affected callables: `functools.reduce`, `itertools.groupby`, `itertools.chain`, `itertools.combinations`, `itertools.count`, `itertools.compress`. ~10 cases through these directly, ~5 cases cascade through their consumers.

### Bucket D — Beyond pure type inference (~58 cases)

These are the cases Ben has previously flagged as **not addressable by type inference alone** — they require value-flow tracking, alias analysis, or dynamic-execution modeling. Each is a known case to come back to with a different analysis functor.

**D.1 — Path-insensitive dict-dispatch (~12 cases).** Function returns different types depending on which literal arg it gets:

```py
# builtins/switch
def func(case):
    switch = {"case1": 1, "case2": "two", "case3": "three"}
    return switch[case]

a = func("case1")  # GT: ["int"]   — pred ["int", "str"]
b = func("case2")  # GT: ["str"]   — pred ["int", "str"]
c = func("case3")  # GT: ["str"]   — pred ["int", "str"]
```

Requires either Literal-type tracking through string args + dict lookup, or per-call-site flow-sensitive narrowing. Pyright handles this via Literal types. **Out of scope for pure inference until we wire literal-aware narrowing.**

**D.2 — Dict-write aliasing (~6 cases).** Successive writes through the same key need alias-flow:

```py
# dicts/assign
d = {"a": func1}
d["a"] = func2     # ← overwrites — analysis can't track that d["a"] now binds func2 exclusively
e = d["a"]()        # GT: ["int"] (return type of func2); pred mixed [int, str]
```

**D.3 — `exec` / `compile` consequences (~6 cases).** Dynamic code execution produces bindings whose names are runtime-determined:

```py
# dynamic/exec
code = "a = 'Hello, world'"
exec(code)         # ← binds `a` at runtime
b = a              # GT: ["str"] for both a and b; analysis sees `a` as NameError
```

`dynamic/compile` is the same pattern via `compile() + exec()`. **Out of scope by decision** — won't model arbitrary Python text execution.

**D.4 — External pip imports (~14 cases).** `typeevalpy_external_module` is a pip-installed package not on the analysis path:

```py
# external/function
from typeevalpy_external_module.ext import function    # ← unresolved import
a = function()                                          # GT: ["Nonetype"], pred ["any"]
```

**Out of scope by decision** — analysis doesn't look at site-packages.

**D.5 — Nested subscript over list-of-dict (~4 cases).** Element-type projection through compound containers:

```py
# builtins/itertools  L5 — GT { variable: "data[0]['name']", exp: ["str"] }
data = [
    {"name": "Alice", "city": "New York"},
    {"name": "Bob", "city": "San Francisco"},
]
```

Requires modeling literal-keyed dict slots within list elements. Doable with effort, but specifically needs literal-keyed projection (the analysis currently widens `dict` to a single value type, losing per-key precision).

**D.6 — Mixed-key dict subscript-of-mixed-type (~4 cases).**

```py
# dicts/call  L12 — GT splits per key: d["a"]→callable, d[1]→callable, d[2]→int
d = {"a": func1, 1: func2, 2: 3}
```

Same Literal-narrowing requirement as D.1 — pred gives union over all values.

**D.7 — Path-insensitive list-element widening (~10 cases).**

```py
# lists/simple — list with mixed callable + int, subscript yields the union
a = [func1, func2, func3]
b = ["Hello"]
b[0] = func4
f = b[0]()      # GT: ["bool"] (return of func4); pred widens
```

Same family as D.2/D.6: requires either Literal-index narrowing or alias tracking.

## Recommended ordering for the next sprint

By expected case-count impact:

1. **Bucket A (108 cases).** `ClassName.method` surfacing + `self.X` write events. Probably the biggest one-week win.
2. **Bucket B.1 (15 cases).** Comprehension/genexpr translation. Mostly a translation-layer fix.
3. **Bucket C (15 cases).** Stdlib stubs for `reduce`, `groupby`, `count`, `chain`. Small targeted analysis work.
4. **Bucket B.2 + B.3 (11 cases).** `map()` call modeling, walrus/chained/starred LHS.

If 1–4 all land cleanly, **the expected ceiling for "pure type inference" Archway is ~750/850 (~88%)** on micro. The remaining ~100 cases are the Bucket-D cohort that requires the abstract-interpretation work (literal narrowing, alias-flow, dict-key projection) or stays accepted as out-of-scope (`exec`/`compile`, external pip imports).

## Comparison to other tools

For sanity-checking that the Bucket-D cases are genuinely hard:

| Tool | Micro EXACT | Bucket-D behavior |
|---|---:|---|
| HeaderGen | 591/850 (69.5%) | Worked harder on path-insensitive dispatch — but doesn't help on external/dynamic |
| Jedi | 476/850 (56.0%) | Punts on dynamic dispatch but handles simple flow |
| **Archway #44** | **599/850 (70.5%)** | Handles most of A/B/C up to current architecture |
| ty (Astral) | 411/850 (48.4%) | Returns `Unknown` on every unhinted call — out-of-scope by design |
| Sonar | 241/850 (28.4%) | Same gradualism as ty, less polish on container types |

Sonar and ty both refuse to infer unhinted return types at all — issue #128 is open on the ty repo. Their gradual-typing philosophy makes the Bucket-D cases moot (they wouldn't try). Archway's bet is the abstract-interpretation path, which means Bucket D is "future work" rather than "won't fix" — but it's correctly tracked as **not type inference**.

## Quick links

- Per-run detail: `archway_report_run44.md`
- Progress history: `archway_progress.md`
- Previous miss analysis: `docs/run36_micro_misses_analysis.md` (run #36, baseline before this loop session)
- Engine + adapter source: `src/archway_benchmarks/engines/archway.py`, `src/archway_benchmarks/benchmarks/archway_adapter.py`
