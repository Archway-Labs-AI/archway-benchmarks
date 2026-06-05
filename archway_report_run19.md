# Run #19 — typeevalpy · archway-translation+archway-analysis

_Created 2026-06-03T00:38:35+00:00_ · _Adapter consumes per-name binding-event arrays (ADR-046 update)_

- **Exact:** 343 / 850 (40.4%)
- **Files processed:** 69 / 153
- **Files sound:** 33 / 153
- **Files complete:** 123 / 153
- **Annotation precision:** 0.831
- **Annotation recall:** 0.404

## Outcome breakdown

| Kind | EXACT | TYPE_MISS | LOCATION_MISS | Total |
| --- | ---: | ---: | ---: | ---: |
| parameter | 54 | 13 | 28 | 95 |
| return | 106 | 5 | 119 | 230 |
| variable | 183 | 52 | 290 | 525 |

## Per-category accuracy (worst first)

| Category | Exact | Total | Rate |
| --- | ---: | ---: | ---: |
| classes | 0 | 122 | 0% |
| exceptions | 0 | 2 | 0% |
| external | 0 | 16 | 0% |
| generators | 0 | 70 | 0% |
| imports | 0 | 25 | 0% |
| mro | 0 | 34 | 0% |
| builtins | 21 | 68 | 31% |
| dynamic | 3 | 9 | 33% |
| assignments | 32 | 82 | 39% |
| returns | 19 | 43 | 44% |
| lists | 30 | 60 | 50% |
| decorators | 30 | 52 | 58% |
| functions | 24 | 37 | 65% |
| args | 31 | 43 | 72% |
| dicts | 82 | 107 | 77% |
| kwargs | 18 | 22 | 82% |
| lambdas | 31 | 34 | 91% |
| direct_calls | 22 | 24 | 92% |

## TYPE_MISS patterns (top by count)

| Expected | Predicted | Count |
| --- | --- | ---: |
| `["int"]` | `["any"]` | 6 |
| `["str"]` | `["NameError"]` | 6 |
| `["callable"]` | `["NameError"]` | 4 |
| `["int"]` | `["TypeError", "int"]` | 4 |
| `["int"]` | `["TypeError"]` | 4 |
| `["int"]` | `["int", "str"]` | 4 |
| `["str"]` | `["TypeError"]` | 4 |
| `["str"]` | `["int", "str"]` | 4 |
| `["float"]` | `["float", "int", "str"]` | 3 |
| `["callable"]` | `["callable", "int"]` | 2 |
| `["int"]` | `["NameError"]` | 2 |
| `["int"]` | `["float", "int", "str"]` | 2 |
| `["str"]` | `["TypeError", "str"]` | 2 |
| `["str"]` | `["float", "int", "str"]` | 2 |
| `["tuple"]` | `["TypeError"]` | 2 |
| `["bool"]` | `["TypeError", "bool"]` | 1 |
| `["callable"]` | `["TypeError", "callable"]` | 1 |
| `["callable"]` | `["dict"]` | 1 |
| `["code"]` | `["TypeError"]` | 1 |
| `["float", "int", "str"]` | `[]` | 1 |
| `["float", "int"]` | `["NameError"]` | 1 |
| `["float"]` | `["TypeError"]` | 1 |
| `["float"]` | `["float", "int"]` | 1 |
| `["int"]` | `["TypeError", "int", "str"]` | 1 |
| `["int"]` | `["any", "int"]` | 1 |
| `["int"]` | `["callable", "int"]` | 1 |
| `["int"]` | `["float", "int"]` | 1 |
| `["list"]` | `["callable", "list"]` | 1 |
| `["map"]` | `["TypeError"]` | 1 |
| `["str"]` | `["TypeError", "int", "str"]` | 1 |
| _(+4 more)_ | | 4 |
| **Total TYPE_MISS** | | **70** |

## Translation errors (84 snippets)

Grouped by error class + leading detail; snippets that translated cleanly but produced no GT-matching wires are NOT in this list.

| Error class | Detail | Count |
| --- | --- | ---: |
| `NotImplementedError` | `translate_stmt: no handler for ClassDef` | 35 |
| `NotImplementedError` | `translate_stmt: no handler for ImportFrom` | 30 |
| `NotImplementedError` | `translate_stmt: no handler for Import` | 7 |
| `NotImplementedError` | `translate_expr: no handler for ListComp` | 4 |
| `NotImplementedError` | `Nested / starred-non-name / subscript / attribute elements in tuple unpacking ar…` | 2 |
| `NotImplementedError` | `translate_expr: no handler for Yield` | 2 |
| `NotImplementedError` | `translate_expr: no handler for GeneratorExp` | 1 |
| `NotImplementedError` | `translate_expr: no handler for NamedExpr` | 1 |
| `NotImplementedError` | `translate_stmt: no handler for Match` | 1 |
| `NotImplementedError` | `translate_stmt: no handler for Nonlocal` | 1 |

### Snippet lists per error class

**`NotImplementedError: translate_stmt: no handler for ClassDef`** (35)

- `classes/assigned_call`
- `classes/assigned_self_call`
- `classes/base_class_attr`
- `classes/base_class_calls_child`
- `classes/call`
- `classes/class_variable`
- `classes/direct_call`
- `classes/inheritance`
- `classes/inheritance_overriding`
- `classes/nested_call`
- `classes/nested_class_calls`
- `classes/parameter_call`
- `classes/return_call`
- `classes/return_call_direct`
- `classes/self_assign_func`
- `classes/self_assignment`
- `classes/self_call`
- `classes/static_method_call`
- `classes/super_class_return`
- `classes/tuple_assignment`
- `decorators/classes`
- `exceptions/raise_assigned`
- `exceptions/raise_attr`
- `functions/static`
- `generators/iter_return`
- `generators/iterable`
- `generators/iterable_assigned`
- `mro/basic`
- `mro/basic_init`
- `mro/parents_same_superclass`
- `mro/self_assignment`
- `mro/super_call`
- `mro/two_parents`
- `mro/two_parents_method_defined`
- `returns/object`

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

**`NotImplementedError: translate_expr: no handler for ListComp`** (4)

- `generators/iter_param`
- `lists/comprehension_if`
- `lists/comprehension_val`
- `lists/nested_comprehension`

**`NotImplementedError: Nested / starred-non-name / subscript / attribute elements in tuple unpacking ar…`** (2)

- `assignments/nested_unpack`
- `assignments/recursive_tuple`

**`NotImplementedError: translate_expr: no handler for Yield`** (2)

- `generators/yield_function`
- `generators/yield_next`

**`NotImplementedError: translate_expr: no handler for GeneratorExp`** (1)

- `assignments/generators`

**`NotImplementedError: translate_expr: no handler for NamedExpr`** (1)

- `assignments/walrus`

**`NotImplementedError: translate_stmt: no handler for Match`** (1)

- `builtins/switch`

**`NotImplementedError: translate_stmt: no handler for Nonlocal`** (1)

- `functions/nested`
