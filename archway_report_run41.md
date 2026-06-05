# Run #41 — typeevalpy_autogen · archway-translation+archway-analysis

_Created 2026-06-05T07:00:24+00:00_ · _loop worktree_

- **Exact:** 51577 / 77268 (66.8%)
- **Files processed:** 5355 / 5453
- **Files sound:** 918 / 5453
- **Files complete:** 1609 / 5453
- **Annotation precision:** 0.842
- **Annotation recall:** 0.668

## Outcome breakdown

| Kind | EXACT | TYPE_MISS | LOCATION_MISS | Total |
| --- | ---: | ---: | ---: | ---: |
| parameter | 785 | 89 | 22 | 896 |
| return | 14519 | 1160 | 2319 | 17998 |
| variable | 36273 | 8432 | 13669 | 58374 |

## Per-category accuracy (worst first)

| Category | Exact | Total | Rate |
| --- | ---: | ---: | ---: |
| dynamic | 21 | 108 | 19% |
| generators | 63 | 259 | 24% |
| builtins | 626 | 1984 | 32% |
| mro | 974 | 2640 | 37% |
| dicts | 1447 | 3469 | 42% |
| imports | 1516 | 3024 | 50% |
| lists | 10747 | 19961 | 54% |
| classes | 3921 | 5600 | 70% |
| decorators | 1115 | 1511 | 74% |
| returns | 2607 | 3453 | 75% |
| assignments | 27018 | 33673 | 80% |
| functions | 459 | 491 | 93% |
| kwargs | 152 | 161 | 94% |
| direct_calls | 154 | 161 | 96% |
| args | 321 | 332 | 97% |
| lambdas | 436 | 441 | 99% |

## TYPE_MISS patterns (top by count)

| Expected | Predicted | Count |
| --- | --- | ---: |
| `["Point"]` | `["any"]` | 420 |
| `["type"]` | `["any"]` | 210 |
| `["callable"]` | `["dict"]` | 132 |
| `["bool"]` | `["TypeError", "bool"]` | 123 |
| `["float"]` | `["TypeError", "float"]` | 123 |
| `["int"]` | `["TypeError", "int"]` | 123 |
| `["str"]` | `["TypeError", "str"]` | 123 |
| `["callable"]` | `["float"]` | 120 |
| `["callable"]` | `["int"]` | 120 |
| `["callable"]` | `["list"]` | 120 |
| `["callable"]` | `["str"]` | 120 |
| `["callable"]` | `["tuple"]` | 120 |
| `["dict"]` | `["TypeError", "dict"]` | 120 |
| `["list"]` | `["TypeError", "list"]` | 120 |
| `["tuple"]` | `["TypeError", "tuple"]` | 120 |
| `["callable"]` | `["callable", "int"]` | 84 |
| `["int"]` | `["any"]` | 78 |
| `["str"]` | `["any"]` | 78 |
| `["bool"]` | `["any"]` | 77 |
| `["float"]` | `["any"]` | 77 |
| `["dict"]` | `["any"]` | 68 |
| `["list"]` | `["any"]` | 68 |
| `["tuple"]` | `["any"]` | 68 |
| `["str"]` | `["float", "str"]` | 59 |
| `["str"]` | `["int", "str"]` | 59 |
| `["int"]` | `["int", "list"]` | 58 |
| `["int"]` | `["dict", "int"]` | 54 |
| `["int"]` | `["dict", "list"]` | 54 |
| `["int"]` | `["dict", "tuple"]` | 54 |
| `["int"]` | `["int", "tuple"]` | 54 |
| _(+354 more)_ | | 6477 |
| **Total TYPE_MISS** | | **9681** |

## Translation errors (91 snippets)

Grouped by error class + leading detail; snippets that translated cleanly but produced no GT-matching wires are NOT in this list.

| Error class | Detail | Count |
| --- | --- | ---: |
| `NotImplementedError` | ``from x import *`` | 84 |
| `CycleError` | `import cycle detected among modules: ['main', 'nested_init']` | 7 |

### Snippet lists per error class

**`NotImplementedError: `from x import *``** (84)

- `imports/import_all_1_10_float_list`
- `imports/import_all_1_11_float_dict`
- `imports/import_all_1_12_float_tuple`
- `imports/import_all_1_13_str_int`
- `imports/import_all_1_14_str_float`
- `imports/import_all_1_15_str_bool`
- `imports/import_all_1_16_str_list`
- `imports/import_all_1_17_str_dict`
- `imports/import_all_1_18_str_tuple`
- `imports/import_all_1_19_bool_int`
- `imports/import_all_1_1_int_float`
- `imports/import_all_1_20_bool_float`
- `imports/import_all_1_21_bool_str`
- `imports/import_all_1_22_bool_list`
- `imports/import_all_1_23_bool_dict`
- `imports/import_all_1_24_bool_tuple`
- `imports/import_all_1_25_list_int`
- `imports/import_all_1_26_list_float`
- `imports/import_all_1_27_list_str`
- `imports/import_all_1_28_list_bool`
- `imports/import_all_1_29_list_dict`
- `imports/import_all_1_2_int_str`
- `imports/import_all_1_30_list_tuple`
- `imports/import_all_1_31_dict_int`
- `imports/import_all_1_32_dict_float`
- `imports/import_all_1_33_dict_str`
- `imports/import_all_1_34_dict_bool`
- `imports/import_all_1_35_dict_list`
- `imports/import_all_1_36_dict_tuple`
- `imports/import_all_1_37_tuple_int`
- `imports/import_all_1_38_tuple_float`
- `imports/import_all_1_39_tuple_str`
- `imports/import_all_1_3_int_bool`
- `imports/import_all_1_40_tuple_bool`
- `imports/import_all_1_41_tuple_list`
- `imports/import_all_1_42_tuple_dict`
- `imports/import_all_1_4_int_list`
- `imports/import_all_1_5_int_dict`
- `imports/import_all_1_6_int_tuple`
- `imports/import_all_1_7_float_int`
- `imports/import_all_1_8_float_str`
- `imports/import_all_1_9_float_bool`
- `imports/submodule_import_all_1_10_float_list`
- `imports/submodule_import_all_1_11_float_dict`
- `imports/submodule_import_all_1_12_float_tuple`
- `imports/submodule_import_all_1_13_str_int`
- `imports/submodule_import_all_1_14_str_float`
- `imports/submodule_import_all_1_15_str_bool`
- `imports/submodule_import_all_1_16_str_list`
- `imports/submodule_import_all_1_17_str_dict`
- `imports/submodule_import_all_1_18_str_tuple`
- `imports/submodule_import_all_1_19_bool_int`
- `imports/submodule_import_all_1_1_int_float`
- `imports/submodule_import_all_1_20_bool_float`
- `imports/submodule_import_all_1_21_bool_str`
- `imports/submodule_import_all_1_22_bool_list`
- `imports/submodule_import_all_1_23_bool_dict`
- `imports/submodule_import_all_1_24_bool_tuple`
- `imports/submodule_import_all_1_25_list_int`
- `imports/submodule_import_all_1_26_list_float`
- `imports/submodule_import_all_1_27_list_str`
- `imports/submodule_import_all_1_28_list_bool`
- `imports/submodule_import_all_1_29_list_dict`
- `imports/submodule_import_all_1_2_int_str`
- `imports/submodule_import_all_1_30_list_tuple`
- `imports/submodule_import_all_1_31_dict_int`
- `imports/submodule_import_all_1_32_dict_float`
- `imports/submodule_import_all_1_33_dict_str`
- `imports/submodule_import_all_1_34_dict_bool`
- `imports/submodule_import_all_1_35_dict_list`
- `imports/submodule_import_all_1_36_dict_tuple`
- `imports/submodule_import_all_1_37_tuple_int`
- `imports/submodule_import_all_1_38_tuple_float`
- `imports/submodule_import_all_1_39_tuple_str`
- `imports/submodule_import_all_1_3_int_bool`
- `imports/submodule_import_all_1_40_tuple_bool`
- `imports/submodule_import_all_1_41_tuple_list`
- `imports/submodule_import_all_1_42_tuple_dict`
- `imports/submodule_import_all_1_4_int_list`
- `imports/submodule_import_all_1_5_int_dict`
- `imports/submodule_import_all_1_6_int_tuple`
- `imports/submodule_import_all_1_7_float_int`
- `imports/submodule_import_all_1_8_float_str`
- `imports/submodule_import_all_1_9_float_bool`

**`CycleError: import cycle detected among modules: ['main', 'nested_init']`** (7)

- `imports/init_import_1_1_int`
- `imports/init_import_1_2_float`
- `imports/init_import_1_3_str`
- `imports/init_import_1_4_bool`
- `imports/init_import_1_5_list`
- `imports/init_import_1_6_dict`
- `imports/init_import_1_7_tuple`
