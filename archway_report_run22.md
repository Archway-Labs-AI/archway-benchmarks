# Run #22 — typeevalpy · archway-translation+archway-analysis

_Created 2026-06-03T06:26:52+00:00_ · _Multi-module GET endpoint live_

- **Exact:** 0 / 850 (0.0%)
- **Files processed:** 0 / 153
- **Files sound:** 0 / 153
- **Files complete:** 153 / 153
- **Annotation precision:** 0.000
- **Annotation recall:** 0.000

## Outcome breakdown

| Kind | EXACT | TYPE_MISS | LOCATION_MISS | Total |
| --- | ---: | ---: | ---: | ---: |
| parameter | 0 | 0 | 95 | 95 |
| return | 0 | 0 | 230 | 230 |
| variable | 0 | 0 | 525 | 525 |

## Per-category accuracy (worst first)

| Category | Exact | Total | Rate |
| --- | ---: | ---: | ---: |
| args | 0 | 43 | 0% |
| assignments | 0 | 82 | 0% |
| builtins | 0 | 68 | 0% |
| classes | 0 | 122 | 0% |
| decorators | 0 | 52 | 0% |
| dicts | 0 | 107 | 0% |
| direct_calls | 0 | 24 | 0% |
| dynamic | 0 | 9 | 0% |
| exceptions | 0 | 2 | 0% |
| external | 0 | 16 | 0% |
| functions | 0 | 37 | 0% |
| generators | 0 | 70 | 0% |
| imports | 0 | 25 | 0% |
| kwargs | 0 | 22 | 0% |
| lambdas | 0 | 34 | 0% |
| lists | 0 | 60 | 0% |
| mro | 0 | 34 | 0% |
| returns | 0 | 43 | 0% |

## TYPE_MISS patterns

_None._

## Translation errors (153 snippets)

Grouped by error class + leading detail; snippets that translated cleanly but produced no GT-matching wires are NOT in this list.

| Error class | Detail | Count |
| --- | --- | ---: |
| `package root not a directory` | `args/assigned_call` | 1 |
| `package root not a directory` | `args/call` | 1 |
| `package root not a directory` | `args/default` | 1 |
| `package root not a directory` | `args/imported_assigned_call` | 1 |
| `package root not a directory` | `args/imported_call` | 1 |
| `package root not a directory` | `args/multiple` | 1 |
| `package root not a directory` | `args/nested_call` | 1 |
| `package root not a directory` | `args/param_call` | 1 |
| `package root not a directory` | `assignments/augmented` | 1 |
| `package root not a directory` | `assignments/chained` | 1 |
| `package root not a directory` | `assignments/generators` | 1 |
| `package root not a directory` | `assignments/nested_unpack` | 1 |
| `package root not a directory` | `assignments/recursive_tuple` | 1 |
| `package root not a directory` | `assignments/starred` | 1 |
| `package root not a directory` | `assignments/tuple` | 1 |
| `package root not a directory` | `assignments/walrus` | 1 |
| `package root not a directory` | `builtins/functions` | 1 |
| `package root not a directory` | `builtins/functools` | 1 |
| `package root not a directory` | `builtins/itertools` | 1 |
| `package root not a directory` | `builtins/map` | 1 |
| `package root not a directory` | `builtins/switch` | 1 |
| `package root not a directory` | `builtins/types` | 1 |
| `package root not a directory` | `builtins/zip` | 1 |
| `package root not a directory` | `classes/abstract_class` | 1 |
| `package root not a directory` | `classes/assigned_call` | 1 |
| `package root not a directory` | `classes/assigned_self_call` | 1 |
| `package root not a directory` | `classes/base_class_attr` | 1 |
| `package root not a directory` | `classes/base_class_calls_child` | 1 |
| `package root not a directory` | `classes/call` | 1 |
| `package root not a directory` | `classes/class_variable` | 1 |
| `package root not a directory` | `classes/direct_call` | 1 |
| `package root not a directory` | `classes/imported_attr_access` | 1 |
| `package root not a directory` | `classes/imported_call` | 1 |
| `package root not a directory` | `classes/imported_call_without_init` | 1 |
| `package root not a directory` | `classes/imported_nested_attr_access` | 1 |
| `package root not a directory` | `classes/inheritance` | 1 |
| `package root not a directory` | `classes/inheritance_overriding` | 1 |
| `package root not a directory` | `classes/nested_call` | 1 |
| `package root not a directory` | `classes/nested_class_calls` | 1 |
| `package root not a directory` | `classes/parameter_call` | 1 |
| `package root not a directory` | `classes/return_call` | 1 |
| `package root not a directory` | `classes/return_call_direct` | 1 |
| `package root not a directory` | `classes/self_assign_func` | 1 |
| `package root not a directory` | `classes/self_assignment` | 1 |
| `package root not a directory` | `classes/self_call` | 1 |
| `package root not a directory` | `classes/static_method_call` | 1 |
| `package root not a directory` | `classes/super_class_return` | 1 |
| `package root not a directory` | `classes/tuple_assignment` | 1 |
| `package root not a directory` | `decorators/assigned` | 1 |
| `package root not a directory` | `decorators/call` | 1 |
| `package root not a directory` | `decorators/classes` | 1 |
| `package root not a directory` | `decorators/nested` | 1 |
| `package root not a directory` | `decorators/nested_decorators` | 1 |
| `package root not a directory` | `decorators/param_call` | 1 |
| `package root not a directory` | `decorators/return` | 1 |
| `package root not a directory` | `decorators/return_different_func` | 1 |
| `package root not a directory` | `dicts/add_key` | 1 |
| `package root not a directory` | `dicts/assign` | 1 |
| `package root not a directory` | `dicts/call` | 1 |
| `package root not a directory` | `dicts/ext_key` | 1 |
| `package root not a directory` | `dicts/merge` | 1 |
| `package root not a directory` | `dicts/merge_pipe` | 1 |
| `package root not a directory` | `dicts/nested` | 1 |
| `package root not a directory` | `dicts/new_key_param` | 1 |
| `package root not a directory` | `dicts/param` | 1 |
| `package root not a directory` | `dicts/param_key` | 1 |
| `package root not a directory` | `dicts/return` | 1 |
| `package root not a directory` | `dicts/return_assign` | 1 |
| `package root not a directory` | `dicts/type_coercion` | 1 |
| `package root not a directory` | `dicts/update` | 1 |
| `package root not a directory` | `dicts/zip` | 1 |
| `package root not a directory` | `direct_calls/assigned_call` | 1 |
| `package root not a directory` | `direct_calls/imported_return_call` | 1 |
| `package root not a directory` | `direct_calls/lambda` | 1 |
| `package root not a directory` | `direct_calls/return_call` | 1 |
| `package root not a directory` | `direct_calls/single_argument` | 1 |
| `package root not a directory` | `direct_calls/with_parameters` | 1 |
| `package root not a directory` | `dynamic/compile` | 1 |
| `package root not a directory` | `dynamic/eval` | 1 |
| `package root not a directory` | `dynamic/exec` | 1 |
| `package root not a directory` | `exceptions/raise_assigned` | 1 |
| `package root not a directory` | `exceptions/raise_attr` | 1 |
| `package root not a directory` | `external/attribute` | 1 |
| `package root not a directory` | `external/attribute_assigned` | 1 |
| `package root not a directory` | `external/cls_parent` | 1 |
| `package root not a directory` | `external/cls_parent_init` | 1 |
| `package root not a directory` | `external/function` | 1 |
| `package root not a directory` | `external/function_asname` | 1 |
| `package root not a directory` | `external/function_assigned` | 1 |
| `package root not a directory` | `functions/assigned_call` | 1 |
| `package root not a directory` | `functions/assigned_call_lit_param` | 1 |
| `package root not a directory` | `functions/call` | 1 |
| `package root not a directory` | `functions/composition` | 1 |
| `package root not a directory` | `functions/default` | 1 |
| `package root not a directory` | `functions/imported_call` | 1 |
| `package root not a directory` | `functions/nested` | 1 |
| `package root not a directory` | `functions/recursive_function` | 1 |
| `package root not a directory` | `functions/static` | 1 |
| `package root not a directory` | `generators/iter_param` | 1 |
| `package root not a directory` | `generators/iter_return` | 1 |
| `package root not a directory` | `generators/iterable` | 1 |
| `package root not a directory` | `generators/iterable_assigned` | 1 |
| `package root not a directory` | `generators/yield_function` | 1 |
| `package root not a directory` | `generators/yield_next` | 1 |
| `package root not a directory` | `imports/chained_import` | 1 |
| `package root not a directory` | `imports/import_all` | 1 |
| `package root not a directory` | `imports/import_as` | 1 |
| `package root not a directory` | `imports/import_from` | 1 |
| `package root not a directory` | `imports/init_func_import` | 1 |
| `package root not a directory` | `imports/init_import` | 1 |
| `package root not a directory` | `imports/parent_import` | 1 |
| `package root not a directory` | `imports/relative_import` | 1 |
| `package root not a directory` | `imports/relative_import_with_name` | 1 |
| `package root not a directory` | `imports/simple_import` | 1 |
| `package root not a directory` | `imports/submodule_import` | 1 |
| `package root not a directory` | `imports/submodule_import_all` | 1 |
| `package root not a directory` | `imports/submodule_import_as` | 1 |
| `package root not a directory` | `imports/submodule_import_from` | 1 |
| `package root not a directory` | `kwargs/assigned_call` | 1 |
| `package root not a directory` | `kwargs/call` | 1 |
| `package root not a directory` | `kwargs/chained_call` | 1 |
| `package root not a directory` | `kwargs/multiple` | 1 |
| `package root not a directory` | `lambdas/call` | 1 |
| `package root not a directory` | `lambdas/calls_parameter` | 1 |
| `package root not a directory` | `lambdas/chained_calls` | 1 |
| `package root not a directory` | `lambdas/composition` | 1 |
| `package root not a directory` | `lambdas/parameter_call` | 1 |
| `package root not a directory` | `lambdas/return_call` | 1 |
| `package root not a directory` | `lists/comprehension_if` | 1 |
| `package root not a directory` | `lists/comprehension_val` | 1 |
| `package root not a directory` | `lists/copy` | 1 |
| `package root not a directory` | `lists/ext_index` | 1 |
| `package root not a directory` | `lists/nested` | 1 |
| `package root not a directory` | `lists/nested_comprehension` | 1 |
| `package root not a directory` | `lists/param_index` | 1 |
| `package root not a directory` | `lists/simple` | 1 |
| `package root not a directory` | `lists/slice` | 1 |
| `package root not a directory` | `lists/unpacking` | 1 |
| `package root not a directory` | `mro/basic` | 1 |
| `package root not a directory` | `mro/basic_init` | 1 |
| `package root not a directory` | `mro/parents_same_superclass` | 1 |
| `package root not a directory` | `mro/self_assignment` | 1 |
| `package root not a directory` | `mro/super_call` | 1 |
| `package root not a directory` | `mro/two_parents` | 1 |
| `package root not a directory` | `mro/two_parents_method_defined` | 1 |
| `package root not a directory` | `returns/call` | 1 |
| `package root not a directory` | `returns/imported_call` | 1 |
| `package root not a directory` | `returns/multiple_types` | 1 |
| `package root not a directory` | `returns/nested_import_call` | 1 |
| `package root not a directory` | `returns/object` | 1 |
| `package root not a directory` | `returns/return_complex` | 1 |
| `package root not a directory` | `returns/return_lambda` | 1 |
| `package root not a directory` | `returns/return_types` | 1 |

### Snippet lists per error class

**`package root not a directory: args/assigned_call`** (1)

- `args/assigned_call`

**`package root not a directory: args/call`** (1)

- `args/call`

**`package root not a directory: args/default`** (1)

- `args/default`

**`package root not a directory: args/imported_assigned_call`** (1)

- `args/imported_assigned_call`

**`package root not a directory: args/imported_call`** (1)

- `args/imported_call`

**`package root not a directory: args/multiple`** (1)

- `args/multiple`

**`package root not a directory: args/nested_call`** (1)

- `args/nested_call`

**`package root not a directory: args/param_call`** (1)

- `args/param_call`

**`package root not a directory: assignments/augmented`** (1)

- `assignments/augmented`

**`package root not a directory: assignments/chained`** (1)

- `assignments/chained`

**`package root not a directory: assignments/generators`** (1)

- `assignments/generators`

**`package root not a directory: assignments/nested_unpack`** (1)

- `assignments/nested_unpack`

**`package root not a directory: assignments/recursive_tuple`** (1)

- `assignments/recursive_tuple`

**`package root not a directory: assignments/starred`** (1)

- `assignments/starred`

**`package root not a directory: assignments/tuple`** (1)

- `assignments/tuple`

**`package root not a directory: assignments/walrus`** (1)

- `assignments/walrus`

**`package root not a directory: builtins/functions`** (1)

- `builtins/functions`

**`package root not a directory: builtins/functools`** (1)

- `builtins/functools`

**`package root not a directory: builtins/itertools`** (1)

- `builtins/itertools`

**`package root not a directory: builtins/map`** (1)

- `builtins/map`

**`package root not a directory: builtins/switch`** (1)

- `builtins/switch`

**`package root not a directory: builtins/types`** (1)

- `builtins/types`

**`package root not a directory: builtins/zip`** (1)

- `builtins/zip`

**`package root not a directory: classes/abstract_class`** (1)

- `classes/abstract_class`

**`package root not a directory: classes/assigned_call`** (1)

- `classes/assigned_call`

**`package root not a directory: classes/assigned_self_call`** (1)

- `classes/assigned_self_call`

**`package root not a directory: classes/base_class_attr`** (1)

- `classes/base_class_attr`

**`package root not a directory: classes/base_class_calls_child`** (1)

- `classes/base_class_calls_child`

**`package root not a directory: classes/call`** (1)

- `classes/call`

**`package root not a directory: classes/class_variable`** (1)

- `classes/class_variable`

**`package root not a directory: classes/direct_call`** (1)

- `classes/direct_call`

**`package root not a directory: classes/imported_attr_access`** (1)

- `classes/imported_attr_access`

**`package root not a directory: classes/imported_call`** (1)

- `classes/imported_call`

**`package root not a directory: classes/imported_call_without_init`** (1)

- `classes/imported_call_without_init`

**`package root not a directory: classes/imported_nested_attr_access`** (1)

- `classes/imported_nested_attr_access`

**`package root not a directory: classes/inheritance`** (1)

- `classes/inheritance`

**`package root not a directory: classes/inheritance_overriding`** (1)

- `classes/inheritance_overriding`

**`package root not a directory: classes/nested_call`** (1)

- `classes/nested_call`

**`package root not a directory: classes/nested_class_calls`** (1)

- `classes/nested_class_calls`

**`package root not a directory: classes/parameter_call`** (1)

- `classes/parameter_call`

**`package root not a directory: classes/return_call`** (1)

- `classes/return_call`

**`package root not a directory: classes/return_call_direct`** (1)

- `classes/return_call_direct`

**`package root not a directory: classes/self_assign_func`** (1)

- `classes/self_assign_func`

**`package root not a directory: classes/self_assignment`** (1)

- `classes/self_assignment`

**`package root not a directory: classes/self_call`** (1)

- `classes/self_call`

**`package root not a directory: classes/static_method_call`** (1)

- `classes/static_method_call`

**`package root not a directory: classes/super_class_return`** (1)

- `classes/super_class_return`

**`package root not a directory: classes/tuple_assignment`** (1)

- `classes/tuple_assignment`

**`package root not a directory: decorators/assigned`** (1)

- `decorators/assigned`

**`package root not a directory: decorators/call`** (1)

- `decorators/call`

**`package root not a directory: decorators/classes`** (1)

- `decorators/classes`

**`package root not a directory: decorators/nested`** (1)

- `decorators/nested`

**`package root not a directory: decorators/nested_decorators`** (1)

- `decorators/nested_decorators`

**`package root not a directory: decorators/param_call`** (1)

- `decorators/param_call`

**`package root not a directory: decorators/return`** (1)

- `decorators/return`

**`package root not a directory: decorators/return_different_func`** (1)

- `decorators/return_different_func`

**`package root not a directory: dicts/add_key`** (1)

- `dicts/add_key`

**`package root not a directory: dicts/assign`** (1)

- `dicts/assign`

**`package root not a directory: dicts/call`** (1)

- `dicts/call`

**`package root not a directory: dicts/ext_key`** (1)

- `dicts/ext_key`

**`package root not a directory: dicts/merge`** (1)

- `dicts/merge`

**`package root not a directory: dicts/merge_pipe`** (1)

- `dicts/merge_pipe`

**`package root not a directory: dicts/nested`** (1)

- `dicts/nested`

**`package root not a directory: dicts/new_key_param`** (1)

- `dicts/new_key_param`

**`package root not a directory: dicts/param`** (1)

- `dicts/param`

**`package root not a directory: dicts/param_key`** (1)

- `dicts/param_key`

**`package root not a directory: dicts/return`** (1)

- `dicts/return`

**`package root not a directory: dicts/return_assign`** (1)

- `dicts/return_assign`

**`package root not a directory: dicts/type_coercion`** (1)

- `dicts/type_coercion`

**`package root not a directory: dicts/update`** (1)

- `dicts/update`

**`package root not a directory: dicts/zip`** (1)

- `dicts/zip`

**`package root not a directory: direct_calls/assigned_call`** (1)

- `direct_calls/assigned_call`

**`package root not a directory: direct_calls/imported_return_call`** (1)

- `direct_calls/imported_return_call`

**`package root not a directory: direct_calls/lambda`** (1)

- `direct_calls/lambda`

**`package root not a directory: direct_calls/return_call`** (1)

- `direct_calls/return_call`

**`package root not a directory: direct_calls/single_argument`** (1)

- `direct_calls/single_argument`

**`package root not a directory: direct_calls/with_parameters`** (1)

- `direct_calls/with_parameters`

**`package root not a directory: dynamic/compile`** (1)

- `dynamic/compile`

**`package root not a directory: dynamic/eval`** (1)

- `dynamic/eval`

**`package root not a directory: dynamic/exec`** (1)

- `dynamic/exec`

**`package root not a directory: exceptions/raise_assigned`** (1)

- `exceptions/raise_assigned`

**`package root not a directory: exceptions/raise_attr`** (1)

- `exceptions/raise_attr`

**`package root not a directory: external/attribute`** (1)

- `external/attribute`

**`package root not a directory: external/attribute_assigned`** (1)

- `external/attribute_assigned`

**`package root not a directory: external/cls_parent`** (1)

- `external/cls_parent`

**`package root not a directory: external/cls_parent_init`** (1)

- `external/cls_parent_init`

**`package root not a directory: external/function`** (1)

- `external/function`

**`package root not a directory: external/function_asname`** (1)

- `external/function_asname`

**`package root not a directory: external/function_assigned`** (1)

- `external/function_assigned`

**`package root not a directory: functions/assigned_call`** (1)

- `functions/assigned_call`

**`package root not a directory: functions/assigned_call_lit_param`** (1)

- `functions/assigned_call_lit_param`

**`package root not a directory: functions/call`** (1)

- `functions/call`

**`package root not a directory: functions/composition`** (1)

- `functions/composition`

**`package root not a directory: functions/default`** (1)

- `functions/default`

**`package root not a directory: functions/imported_call`** (1)

- `functions/imported_call`

**`package root not a directory: functions/nested`** (1)

- `functions/nested`

**`package root not a directory: functions/recursive_function`** (1)

- `functions/recursive_function`

**`package root not a directory: functions/static`** (1)

- `functions/static`

**`package root not a directory: generators/iter_param`** (1)

- `generators/iter_param`

**`package root not a directory: generators/iter_return`** (1)

- `generators/iter_return`

**`package root not a directory: generators/iterable`** (1)

- `generators/iterable`

**`package root not a directory: generators/iterable_assigned`** (1)

- `generators/iterable_assigned`

**`package root not a directory: generators/yield_function`** (1)

- `generators/yield_function`

**`package root not a directory: generators/yield_next`** (1)

- `generators/yield_next`

**`package root not a directory: imports/chained_import`** (1)

- `imports/chained_import`

**`package root not a directory: imports/import_all`** (1)

- `imports/import_all`

**`package root not a directory: imports/import_as`** (1)

- `imports/import_as`

**`package root not a directory: imports/import_from`** (1)

- `imports/import_from`

**`package root not a directory: imports/init_func_import`** (1)

- `imports/init_func_import`

**`package root not a directory: imports/init_import`** (1)

- `imports/init_import`

**`package root not a directory: imports/parent_import`** (1)

- `imports/parent_import`

**`package root not a directory: imports/relative_import`** (1)

- `imports/relative_import`

**`package root not a directory: imports/relative_import_with_name`** (1)

- `imports/relative_import_with_name`

**`package root not a directory: imports/simple_import`** (1)

- `imports/simple_import`

**`package root not a directory: imports/submodule_import`** (1)

- `imports/submodule_import`

**`package root not a directory: imports/submodule_import_all`** (1)

- `imports/submodule_import_all`

**`package root not a directory: imports/submodule_import_as`** (1)

- `imports/submodule_import_as`

**`package root not a directory: imports/submodule_import_from`** (1)

- `imports/submodule_import_from`

**`package root not a directory: kwargs/assigned_call`** (1)

- `kwargs/assigned_call`

**`package root not a directory: kwargs/call`** (1)

- `kwargs/call`

**`package root not a directory: kwargs/chained_call`** (1)

- `kwargs/chained_call`

**`package root not a directory: kwargs/multiple`** (1)

- `kwargs/multiple`

**`package root not a directory: lambdas/call`** (1)

- `lambdas/call`

**`package root not a directory: lambdas/calls_parameter`** (1)

- `lambdas/calls_parameter`

**`package root not a directory: lambdas/chained_calls`** (1)

- `lambdas/chained_calls`

**`package root not a directory: lambdas/composition`** (1)

- `lambdas/composition`

**`package root not a directory: lambdas/parameter_call`** (1)

- `lambdas/parameter_call`

**`package root not a directory: lambdas/return_call`** (1)

- `lambdas/return_call`

**`package root not a directory: lists/comprehension_if`** (1)

- `lists/comprehension_if`

**`package root not a directory: lists/comprehension_val`** (1)

- `lists/comprehension_val`

**`package root not a directory: lists/copy`** (1)

- `lists/copy`

**`package root not a directory: lists/ext_index`** (1)

- `lists/ext_index`

**`package root not a directory: lists/nested`** (1)

- `lists/nested`

**`package root not a directory: lists/nested_comprehension`** (1)

- `lists/nested_comprehension`

**`package root not a directory: lists/param_index`** (1)

- `lists/param_index`

**`package root not a directory: lists/simple`** (1)

- `lists/simple`

**`package root not a directory: lists/slice`** (1)

- `lists/slice`

**`package root not a directory: lists/unpacking`** (1)

- `lists/unpacking`

**`package root not a directory: mro/basic`** (1)

- `mro/basic`

**`package root not a directory: mro/basic_init`** (1)

- `mro/basic_init`

**`package root not a directory: mro/parents_same_superclass`** (1)

- `mro/parents_same_superclass`

**`package root not a directory: mro/self_assignment`** (1)

- `mro/self_assignment`

**`package root not a directory: mro/super_call`** (1)

- `mro/super_call`

**`package root not a directory: mro/two_parents`** (1)

- `mro/two_parents`

**`package root not a directory: mro/two_parents_method_defined`** (1)

- `mro/two_parents_method_defined`

**`package root not a directory: returns/call`** (1)

- `returns/call`

**`package root not a directory: returns/imported_call`** (1)

- `returns/imported_call`

**`package root not a directory: returns/multiple_types`** (1)

- `returns/multiple_types`

**`package root not a directory: returns/nested_import_call`** (1)

- `returns/nested_import_call`

**`package root not a directory: returns/object`** (1)

- `returns/object`

**`package root not a directory: returns/return_complex`** (1)

- `returns/return_complex`

**`package root not a directory: returns/return_lambda`** (1)

- `returns/return_lambda`

**`package root not a directory: returns/return_types`** (1)

- `returns/return_types`
