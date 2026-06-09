# Builtins worth handling — micro-benchmark impact

Ranked by how many TypeEvalPy micro-benchmark misses they close (directly or via cascade) in the run #6 state. Source: `archway_report_run6.md` TYPE_MISS breakdown.

## Tier 1 — flat signatures, 21 direct miss cases

These are simple no-context return-type tables. Modeling them removes the `TypeError`/`NameError` leakage that currently makes calls to unbound builtin names propagate as inferred values.

| Builtin | GT return | Snippets |
|---|---|---|
| `len(seq)` | `int` | `builtins/functions:5` |
| `sum(seq)` | `int` | `builtins/functions:7` |
| `max(seq)` | element type | `builtins/functions:9` |
| `min(seq)` | element type | `builtins/functions:11` |
| `sorted(seq)` | `list` | `builtins/functions:13` |
| `any(seq)` | `bool` | `builtins/functions:15` |
| `all(seq)` | `bool` | `builtins/functions:17` |
| `zip(a, b, …)` | `zip` (iterator of tuples) | `builtins/zip`, `dicts/zip` |
| `list(iter)` | `list` (carrying element type) | `builtins/zip:9`, `dicts/zip:6` |
| `dict(iter_of_pairs)` | `dict` | `dicts/zip:6` |

## Tier 2 — string/list methods, 4 direct miss cases

Same family but invoked via attribute-call. Requires the translator to route method calls; once that's plumbed, these are again flat signatures.

| Method | Receiver → GT return | Snippets |
|---|---|---|
| `str.join(iter)` | `str` | `builtins/types:3` |
| `str.split(sep)` | `list` | `builtins/types:5` |
| `list.copy()` | `list` (same element type) | `lists/copy:3` |
| `list.pop()` | element type | `assignments/walrus:6` |

## Cascade effects from Tier 1 + Tier 2 — ~8 more cases

Once builtins stop raising at interpretation time, the `TypeError` no longer leaks into:

- `dicts/call:14–15` (2 cases)
- `dicts/zip:6` (already counted in Tier 1)
- `lists/nested:15–16` (2 cases)
- `lists/simple:30` (1 case)
- `builtins/zip:9` `result = list(combined)` second-order (already counted)

Estimated total impact of Tier 1 + Tier 2 + cascade: **~33 cases on micro**.

## Tier 3 — higher-effort, ~10 more direct cases

| Builtin | Notes | Snippets |
|---|---|---|
| `range(n)` / `range(a, b)` | iterator of `int`. Used in many for-loops and comprehensions across the benchmark. | `lists/comprehension_val`, `lists/nested_comprehension`, `generators/yield_next`, etc. |
| `next(iter)` | element type of iterator. | `generators/yield_next:15,17` |
| `map(f, iter)` | iterator carrying `f`'s return type. Needs higher-order modeling — thread the callable arg's return through. | `builtins/map` |
| `functools.reduce(f, iter)` | `f`'s return type. Same higher-order shape as map. | `builtins/functools` |

`range` and `next` are mechanical flat signatures (just need the iterator-element semantics from Tier 1's `zip`). `map` and `reduce` require routing a callable parameter's signature into the return — worth a separate pass once core indirect-call propagation is rock-solid.

## Out of scope / lowest priority

- `compile`, `eval`, `exec` — dynamic codegen, not statically inferable. Treat as `any` or explicit error.
- Most of `itertools.*` — large surface, low GT yield on this benchmark.

## Suggested implementation order

1. **Tier 1** (10 functions, ~21 direct + cascade cases). Single signature table; biggest unblocker.
2. **Tier 2** (4 methods, ~4 direct + walrus unblock). Requires str/list method-dispatch path.
3. **Tier 3 — `range` and `next`** (~6 cases). Mechanical once iterator semantics from Tier 1 exist.
4. **Tier 3 — `map` and `reduce`** (~2 cases plus generalization). Higher-order callable threading; tackle when indirect-call propagation is stable.
