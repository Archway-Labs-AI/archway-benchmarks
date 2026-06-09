# Run #33 — typeevalpy · archway-translation+archway-analysis

_Created 2026-06-04T04:57:55+00:00_

- **Exact:** 509 / 850 (59.9%)
- **Files processed:** 137 / 153
- **Files sound:** 55 / 153
- **Files complete:** 107 / 153
- **Annotation precision:** 0.833
- **Annotation recall:** 0.599

## Outcome breakdown

| Kind | EXACT | TYPE_MISS | LOCATION_MISS | Total |
| --- | ---: | ---: | ---: | ---: |
| parameter | 69 | 6 | 20 | 95 |
| return | 128 | 8 | 94 | 230 |
| variable | 312 | 88 | 125 | 525 |

## Per-category accuracy (worst first)

| Category | Exact | Total | Rate |
| --- | ---: | ---: | ---: |
| exceptions | 0 | 2 | 0% |
| generators | 0 | 70 | 0% |
| external | 2 | 16 | 12% |
| dynamic | 3 | 9 | 33% |
| mro | 13 | 34 | 38% |
| builtins | 33 | 68 | 49% |
| assignments | 40 | 82 | 49% |
| classes | 60 | 122 | 49% |
| lists | 37 | 60 | 62% |
| imports | 17 | 25 | 68% |
| returns | 31 | 43 | 72% |
| functions | 28 | 37 | 76% |
| decorators | 40 | 52 | 77% |
| dicts | 86 | 107 | 80% |
| args | 41 | 43 | 95% |
| kwargs | 21 | 22 | 95% |
| direct_calls | 23 | 24 | 96% |
| lambdas | 34 | 34 | 100% |

## TYPE_MISS patterns (top by count)

| Expected | Predicted | Count |
| --- | --- | ---: |
| `["int"]` | `["TypeError"]` | 8 |
| `["str"]` | `["any"]` | 7 |
| `["int"]` | `["any"]` | 6 |
| `["str"]` | `["int", "str"]` | 5 |
| `["int"]` | `["int", "str"]` | 4 |
| `["str"]` | `["dict"]` | 4 |
| `["Nonetype"]` | `["any"]` | 3 |
| `["float"]` | `["float", "int", "str"]` | 3 |
| `["str"]` | `["TypeError"]` | 3 |
| `["Point"]` | `["any"]` | 2 |
| `["callable"]` | `["any"]` | 2 |
| `["callable"]` | `["callable", "int"]` | 2 |
| `["float"]` | `["any"]` | 2 |
| `["int"]` | `["float", "int", "str"]` | 2 |
| `["int"]` | `["tuple"]` | 2 |
| `["set"]` | `["TypeError"]` | 2 |
| `["str"]` | `["NameError"]` | 2 |
| `["str"]` | `["float", "int", "str"]` | 2 |
| `["str"]` | `["tuple"]` | 2 |
| `["typeevalpy_external_module.ext.Cls"]` | `["any"]` | 2 |
| `["MyClass"]` | `["NewClass"]` | 1 |
| `["bool"]` | `["TypeError", "bool"]` | 1 |
| `["callable"]` | `["TypeError", "callable"]` | 1 |
| `["callable"]` | `["dict"]` | 1 |
| `["code"]` | `["TypeError"]` | 1 |
| `["float", "int", "str"]` | `[]` | 1 |
| `["float"]` | `["TypeError"]` | 1 |
| `["float"]` | `["float", "int"]` | 1 |
| `["int"]` | `["TypeError", "int", "str"]` | 1 |
| `["int"]` | `["TypeError", "int"]` | 1 |
| _(+27 more)_ | | 27 |
| **Total TYPE_MISS** | | **102** |

## Translation errors (16 snippets)

Grouped by error class + leading detail; snippets that translated cleanly but produced no GT-matching wires are NOT in this list.

| Error class | Detail | Count |
| --- | --- | ---: |
| `NotImplementedError` | `translate_stmt: no handler for Raise` | 5 |
| `NotImplementedError` | `translate_expr: no handler for Yield` | 2 |
| `NotImplementedError` | ``from x import *`` | 2 |
| `NotImplementedError` | `translate_expr: no handler for GeneratorExp` | 1 |
| `ValueError` | `unpack_binding: no _last_result to destructure. The RHS expression must produce…` | 1 |
| `NotImplementedError` | `translate_expr: no handler for NamedExpr` | 1 |
| `NotImplementedError` | `translate_stmt: no handler for Match` | 1 |
| `NotImplementedError` | `translate_stmt: no handler for Nonlocal` | 1 |
| `NotImplementedError` | `Subscript / attribute / starred-non-name elements in tuple unpacking are not yet…` | 1 |
| `CycleError` | `import cycle detected among modules: ['main', 'nested_init']` | 1 |

### Snippet lists per error class

**`NotImplementedError: translate_stmt: no handler for Raise`** (5)

- `exceptions/raise_assigned`
- `exceptions/raise_attr`
- `generators/iter_param`
- `generators/iter_return`
- `generators/iterable_assigned`

**`NotImplementedError: translate_expr: no handler for Yield`** (2)

- `generators/yield_function`
- `generators/yield_next`

**`NotImplementedError: `from x import *``** (2)

- `imports/import_all`
- `imports/submodule_import_all`

**`NotImplementedError: translate_expr: no handler for GeneratorExp`** (1)

- `assignments/generators`

**`ValueError: unpack_binding: no _last_result to destructure. The RHS expression must produce…`** (1)

- `assignments/recursive_tuple`

**`NotImplementedError: translate_expr: no handler for NamedExpr`** (1)

- `assignments/walrus`

**`NotImplementedError: translate_stmt: no handler for Match`** (1)

- `builtins/switch`

**`NotImplementedError: translate_stmt: no handler for Nonlocal`** (1)

- `functions/nested`

**`NotImplementedError: Subscript / attribute / starred-non-name elements in tuple unpacking are not yet…`** (1)

- `generators/iterable`

**`CycleError: import cycle detected among modules: ['main', 'nested_init']`** (1)

- `imports/init_import`
