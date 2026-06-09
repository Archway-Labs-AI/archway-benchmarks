# Run #20 — typeevalpy · archway-translation+archway-analysis

_Created 2026-06-03T05:00:54+00:00_ · _Quick-support batch_

- **Exact:** 398 / 850 (46.8%)
- **Files processed:** 103 / 153
- **Files sound:** 35 / 153
- **Files complete:** 114 / 153
- **Annotation precision:** 0.836
- **Annotation recall:** 0.468

## Outcome breakdown

| Kind | EXACT | TYPE_MISS | LOCATION_MISS | Total |
| --- | ---: | ---: | ---: | ---: |
| parameter | 54 | 19 | 22 | 95 |
| return | 114 | 7 | 109 | 230 |
| variable | 230 | 52 | 243 | 525 |

## Per-category accuracy (worst first)

| Category | Exact | Total | Rate |
| --- | ---: | ---: | ---: |
| exceptions | 0 | 2 | 0% |
| external | 0 | 16 | 0% |
| generators | 0 | 70 | 0% |
| imports | 0 | 25 | 0% |
| mro | 6 | 34 | 18% |
| classes | 28 | 122 | 23% |
| dynamic | 3 | 9 | 33% |
| builtins | 23 | 68 | 34% |
| returns | 19 | 43 | 44% |
| assignments | 40 | 82 | 49% |
| lists | 34 | 60 | 57% |
| decorators | 31 | 52 | 60% |
| functions | 24 | 37 | 65% |
| dicts | 82 | 107 | 77% |
| args | 35 | 43 | 81% |
| kwargs | 20 | 22 | 91% |
| lambdas | 31 | 34 | 91% |
| direct_calls | 22 | 24 | 92% |

## TYPE_MISS patterns (top by count)

| Expected | Predicted | Count |
| --- | --- | ---: |
| `["int"]` | `["TypeError"]` | 8 |
| `["callable"]` | `["NameError"]` | 7 |
| `["int"]` | `["any"]` | 6 |
| `["str"]` | `["NameError"]` | 6 |
| `["int"]` | `["int", "str"]` | 4 |
| `["str"]` | `["int", "str"]` | 4 |
| `["float"]` | `["float", "int", "str"]` | 3 |
| `["str"]` | `["TypeError"]` | 3 |
| `["callable"]` | `["callable", "int"]` | 2 |
| `["int"]` | `["NameError"]` | 2 |
| `["int"]` | `["float", "int", "str"]` | 2 |
| `["int"]` | `["tuple"]` | 2 |
| `["str"]` | `["any"]` | 2 |
| `["str"]` | `["float", "int", "str"]` | 2 |
| `["str"]` | `["tuple"]` | 2 |
| `["Person"]` | `[]` | 1 |
| `["bool"]` | `["TypeError", "bool"]` | 1 |
| `["callable"]` | `["TypeError", "callable"]` | 1 |
| `["callable"]` | `["dict"]` | 1 |
| `["code"]` | `["TypeError"]` | 1 |
| `["float", "int", "str"]` | `[]` | 1 |
| `["float", "int"]` | `["NameError"]` | 1 |
| `["float"]` | `["TypeError"]` | 1 |
| `["float"]` | `["float", "int"]` | 1 |
| `["int"]` | `["TypeError", "int", "str"]` | 1 |
| `["int"]` | `["TypeError", "int"]` | 1 |
| `["int"]` | `["any", "int"]` | 1 |
| `["int"]` | `["callable", "int"]` | 1 |
| `["int"]` | `["float", "int"]` | 1 |
| `["int"]` | `["str"]` | 1 |
| _(+8 more)_ | | 8 |
| **Total TYPE_MISS** | | **78** |

## Translation errors (50 snippets)

Grouped by error class + leading detail; snippets that translated cleanly but produced no GT-matching wires are NOT in this list.

| Error class | Detail | Count |
| --- | --- | ---: |
| `NotImplementedError` | `translate_stmt: no handler for ImportFrom` | 30 |
| `NotImplementedError` | `translate_stmt: no handler for Import` | 7 |
| `NotImplementedError` | `translate_stmt: no handler for Raise` | 5 |
| `NotImplementedError` | `translate_expr: no handler for Yield` | 2 |
| `NotImplementedError` | `translate_expr: no handler for GeneratorExp` | 1 |
| `ValueError` | `unpack_binding: no _last_result to destructure. The RHS expression must produce…` | 1 |
| `NotImplementedError` | `translate_expr: no handler for NamedExpr` | 1 |
| `NotImplementedError` | `translate_stmt: no handler for Match` | 1 |
| `NotImplementedError` | `translate_stmt: no handler for Nonlocal` | 1 |
| `NotImplementedError` | `Subscript / attribute / starred-non-name elements in tuple unpacking are not yet…` | 1 |

### Snippet lists per error class

**`NotImplementedError: translate_stmt: no handler for ImportFrom`** (30)

- `args/imported_assigned_call`
- `args/imported_call`
- `builtins/functools`
- `classes/abstract_class`
- `classes/imported_call`
- `classes/imported_call_without_init`
- `classes/imported_nested_attr_access`
- `dicts/ext_key`
- `direct_calls/imported_return_call`
- `external/attribute`
- `external/attribute_assigned`
- `external/cls_parent`
- `external/cls_parent_init`
- `external/function`
- `external/function_asname`
- `external/function_assigned`
- `functions/imported_call`
- `imports/chained_import`
- `imports/import_all`
- `imports/import_from`
- `imports/init_func_import`
- `imports/init_import`
- `imports/parent_import`
- `imports/relative_import_with_name`
- `imports/submodule_import_all`
- `imports/submodule_import_from`
- `lists/ext_index`
- `returns/imported_call`
- `returns/nested_import_call`
- `returns/return_types`

**`NotImplementedError: translate_stmt: no handler for Import`** (7)

- `builtins/itertools`
- `classes/imported_attr_access`
- `imports/import_as`
- `imports/relative_import`
- `imports/simple_import`
- `imports/submodule_import`
- `imports/submodule_import_as`

**`NotImplementedError: translate_stmt: no handler for Raise`** (5)

- `exceptions/raise_assigned`
- `exceptions/raise_attr`
- `generators/iter_param`
- `generators/iter_return`
- `generators/iterable_assigned`

**`NotImplementedError: translate_expr: no handler for Yield`** (2)

- `generators/yield_function`
- `generators/yield_next`

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
