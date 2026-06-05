# Run #21 — typeevalpy · archway-translation+archway-analysis

_Created 2026-06-03T05:38:18+00:00_ · _Adapter handles instance + class element kinds_

- **Exact:** 449 / 850 (52.8%)
- **Files processed:** 103 / 153
- **Files sound:** 39 / 153
- **Files complete:** 124 / 153
- **Annotation precision:** 0.882
- **Annotation recall:** 0.528

## Outcome breakdown

| Kind | EXACT | TYPE_MISS | LOCATION_MISS | Total |
| --- | ---: | ---: | ---: | ---: |
| parameter | 69 | 5 | 21 | 95 |
| return | 117 | 4 | 109 | 230 |
| variable | 263 | 51 | 211 | 525 |

## Per-category accuracy (worst first)

| Category | Exact | Total | Rate |
| --- | ---: | ---: | ---: |
| exceptions | 0 | 2 | 0% |
| external | 0 | 16 | 0% |
| generators | 0 | 70 | 0% |
| imports | 0 | 25 | 0% |
| dynamic | 3 | 9 | 33% |
| builtins | 23 | 68 | 34% |
| mro | 13 | 34 | 38% |
| classes | 54 | 122 | 44% |
| assignments | 40 | 82 | 49% |
| returns | 21 | 43 | 49% |
| lists | 34 | 60 | 57% |
| functions | 26 | 37 | 70% |
| dicts | 82 | 107 | 77% |
| decorators | 40 | 52 | 77% |
| args | 36 | 43 | 84% |
| direct_calls | 22 | 24 | 92% |
| kwargs | 21 | 22 | 95% |
| lambdas | 34 | 34 | 100% |

## TYPE_MISS patterns (top by count)

| Expected | Predicted | Count |
| --- | --- | ---: |
| `["int"]` | `["TypeError"]` | 8 |
| `["int"]` | `["int", "str"]` | 4 |
| `["str"]` | `["int", "str"]` | 4 |
| `["float"]` | `["float", "int", "str"]` | 3 |
| `["int"]` | `["any"]` | 3 |
| `["str"]` | `["TypeError"]` | 3 |
| `["callable"]` | `["callable", "int"]` | 2 |
| `["int"]` | `["float", "int", "str"]` | 2 |
| `["int"]` | `["tuple"]` | 2 |
| `["str"]` | `["NameError"]` | 2 |
| `["str"]` | `["any"]` | 2 |
| `["str"]` | `["float", "int", "str"]` | 2 |
| `["str"]` | `["tuple"]` | 2 |
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
| `["int"]` | `["any", "int"]` | 1 |
| `["int"]` | `["callable", "int"]` | 1 |
| `["int"]` | `["float", "int"]` | 1 |
| `["int"]` | `["str"]` | 1 |
| `["list"]` | `["callable", "list"]` | 1 |
| `["map"]` | `["TypeError"]` | 1 |
| `["str"]` | `["AttributeError"]` | 1 |
| _(+4 more)_ | | 4 |
| **Total TYPE_MISS** | | **60** |

## Translation errors (50 snippets)

Grouped by error class + leading detail; snippets that translated cleanly but produced no GT-matching wires are NOT in this list.

| Error class | Detail | Count |
| --- | --- | ---: |
| `NotImplementedError` | `type_signatures: no handler for tag StructuralTag` | 35 |
| `NotImplementedError` | `translate_stmt: no handler for Raise` | 5 |
| `NotImplementedError` | `translate_expr: no handler for Yield` | 2 |
| `NotImplementedError` | ``from x import *`` | 2 |
| `NotImplementedError` | `translate_expr: no handler for GeneratorExp` | 1 |
| `ValueError` | `unpack_binding: no _last_result to destructure. The RHS expression must produce…` | 1 |
| `NotImplementedError` | `translate_expr: no handler for NamedExpr` | 1 |
| `NotImplementedError` | `translate_stmt: no handler for Match` | 1 |
| `NotImplementedError` | `translate_stmt: no handler for Nonlocal` | 1 |
| `NotImplementedError` | `Subscript / attribute / starred-non-name elements in tuple unpacking are not yet…` | 1 |

### Snippet lists per error class

**`NotImplementedError: type_signatures: no handler for tag StructuralTag`** (35)

- `args/imported_assigned_call`
- `args/imported_call`
- `builtins/functools`
- `builtins/itertools`
- `classes/abstract_class`
- `classes/imported_attr_access`
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
- `imports/import_as`
- `imports/import_from`
- `imports/init_func_import`
- `imports/init_import`
- `imports/parent_import`
- `imports/relative_import`
- `imports/relative_import_with_name`
- `imports/simple_import`
- `imports/submodule_import`
- `imports/submodule_import_as`
- `imports/submodule_import_from`
- `lists/ext_index`
- `returns/imported_call`
- `returns/nested_import_call`
- `returns/return_types`

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
