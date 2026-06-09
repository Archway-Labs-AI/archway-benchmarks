# Run #7 — typeevalpy · archway-translation+archway-analysis

_Created 2026-06-02T05:34:33+00:00_ · _End-of-day snapshot_

- **Exact:** 242 / 850 (28.5%)
- **Files processed:** 49 / 153
- **Files sound:** 25 / 153
- **Files complete:** 133 / 153
- **Annotation precision:** 0.840
- **Annotation recall:** 0.285

## Outcome breakdown

| Kind | EXACT | TYPE_MISS | LOCATION_MISS | Total |
| --- | ---: | ---: | ---: | ---: |
| parameter | 29 | 1 | 65 | 95 |
| return | 84 | 1 | 145 | 230 |
| variable | 129 | 44 | 352 | 525 |

## Per-category accuracy (worst first)

| Category | Exact | Total | Rate |
| --- | ---: | ---: | ---: |
| classes | 0 | 122 | 0% |
| exceptions | 0 | 2 | 0% |
| external | 0 | 16 | 0% |
| generators | 0 | 70 | 0% |
| imports | 0 | 25 | 0% |
| lambdas | 0 | 34 | 0% |
| mro | 0 | 34 | 0% |
| builtins | 9 | 68 | 13% |
| assignments | 11 | 82 | 13% |
| decorators | 14 | 52 | 27% |
| returns | 14 | 43 | 33% |
| dynamic | 3 | 9 | 33% |
| lists | 27 | 60 | 45% |
| args | 28 | 43 | 65% |
| dicts | 74 | 107 | 69% |
| functions | 26 | 37 | 70% |
| kwargs | 17 | 22 | 77% |
| direct_calls | 19 | 24 | 79% |

## TYPE_MISS patterns (top by count)

| Expected | Predicted | Count |
| --- | --- | ---: |
| `["int"]` | `["TypeError"]` | 4 |
| `["int"]` | `["int", "str"]` | 4 |
| `["int"]` | `["str"]` | 4 |
| `["str"]` | `["int", "str"]` | 3 |
| `["bool"]` | `["TypeError"]` | 2 |
| `["callable"]` | `["callable", "int"]` | 2 |
| `["float"]` | `["float", "int", "str"]` | 2 |
| `["list"]` | `["TypeError"]` | 2 |
| `["str"]` | `["NameError", "TypeError"]` | 2 |
| `["str"]` | `["NameError"]` | 2 |
| `["bool"]` | `["TypeError", "bool"]` | 1 |
| `["callable"]` | `["TypeError", "callable"]` | 1 |
| `["callable"]` | `["any"]` | 1 |
| `["callable"]` | `["callable", "dict"]` | 1 |
| `["callable"]` | `["dict"]` | 1 |
| `["callable"]` | `["str"]` | 1 |
| `["code"]` | `["TypeError"]` | 1 |
| `["dict"]` | `["TypeError"]` | 1 |
| `["int"]` | `["TypeError", "int", "str"]` | 1 |
| `["int"]` | `["TypeError", "int"]` | 1 |
| `["int"]` | `["any", "int"]` | 1 |
| `["int"]` | `["callable", "int"]` | 1 |
| `["int"]` | `["float", "int", "str"]` | 1 |
| `["list"]` | `["callable", "list"]` | 1 |
| `["str"]` | `["TypeError", "int", "str"]` | 1 |
| `["str"]` | `["TypeError"]` | 1 |
| `["str"]` | `["float", "int", "str"]` | 1 |
| `["str"]` | `["int"]` | 1 |
| `["zip"]` | `["TypeError"]` | 1 |
| **Total TYPE_MISS** | | **46** |

## Translation errors (104 snippets)

Grouped by error class + leading detail; snippets that translated cleanly but produced no GT-matching wires are NOT in this list.

| Error class | Detail | Count |
| --- | --- | ---: |
| `NotImplementedError` | `translate_stmt: no handler for ClassDef` | 35 |
| `NotImplementedError` | `translate_stmt: no handler for ImportFrom` | 30 |
| `NotImplementedError` | `translate_stmt: no handler for Import` | 7 |
| `IndexError` | `list index out of range` | 6 |
| `NotImplementedError` | `translate_expr: no handler for Lambda` | 6 |
| `NotImplementedError` | `translate_expr: no handler for ListComp` | 4 |
| `NotImplementedError` | `Nested / starred / subscript / attribute targets in tuple unpacking are not yet…` | 3 |
| `TypeError` | `cannot serialize lattice element: AmbientElt` | 3 |
| `NotImplementedError` | `translate_stmt: no handler for For` | 2 |
| `NotImplementedError` | `type_signatures: no handler for tag StructuralTag` | 2 |
| `NotImplementedError` | `translate_expr: no handler for Yield` | 2 |
| `NotImplementedError` | `translate_expr: no handler for GeneratorExp` | 1 |
| `TypeError` | `Unknown tag type: TupleTag` | 1 |
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

**`IndexError: list index out of range`** (6)

- `assignments/walrus`
- `builtins/types`
- `dicts/update`
- `direct_calls/lambda`
- `lambdas/composition`
- `lists/copy`

**`NotImplementedError: translate_expr: no handler for Lambda`** (6)

- `lambdas/call`
- `lambdas/calls_parameter`
- `lambdas/chained_calls`
- `lambdas/parameter_call`
- `lambdas/return_call`
- `returns/return_lambda`

**`NotImplementedError: translate_expr: no handler for ListComp`** (4)

- `generators/iter_param`
- `lists/comprehension_if`
- `lists/comprehension_val`
- `lists/nested_comprehension`

**`NotImplementedError: Nested / starred / subscript / attribute targets in tuple unpacking are not yet…`** (3)

- `assignments/nested_unpack`
- `assignments/recursive_tuple`
- `assignments/starred`

**`TypeError: cannot serialize lattice element: AmbientElt`** (3)

- `decorators/call`
- `decorators/return_different_func`
- `dicts/new_key_param`

**`NotImplementedError: translate_stmt: no handler for For`** (2)

- `args/multiple`
- `kwargs/multiple`

**`NotImplementedError: type_signatures: no handler for tag StructuralTag`** (2)

- `builtins/map`
- `lists/unpacking`

**`NotImplementedError: translate_expr: no handler for Yield`** (2)

- `generators/yield_function`
- `generators/yield_next`

**`NotImplementedError: translate_expr: no handler for GeneratorExp`** (1)

- `assignments/generators`

**`TypeError: Unknown tag type: TupleTag`** (1)

- `assignments/tuple`

**`NotImplementedError: translate_stmt: no handler for Match`** (1)

- `builtins/switch`

**`NotImplementedError: translate_stmt: no handler for Nonlocal`** (1)

- `functions/nested`
