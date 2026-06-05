# Run #45 — typeevalpy_autogen · archway-translation+archway-analysis

_Created 2026-06-05T17:05:49+00:00_ · _loop worktree_

- **Exact:** 52266 / 77268 (67.6%)
- **Files processed:** 5439 / 5453
- **Files sound:** 1014 / 5453
- **Files complete:** 1694 / 5453
- **Annotation precision:** 0.845
- **Annotation recall:** 0.676

## Outcome breakdown

| Kind | EXACT | TYPE_MISS | LOCATION_MISS | Total |
| --- | ---: | ---: | ---: | ---: |
| parameter | 795 | 89 | 12 | 896 |
| return | 14519 | 1160 | 2319 | 17998 |
| variable | 36952 | 8347 | 13075 | 58374 |

## Per-category accuracy (worst first)

| Category | Exact | Total | Rate |
| --- | ---: | ---: | ---: |
| dynamic | 21 | 108 | 19% |
| generators | 63 | 259 | 24% |
| builtins | 626 | 1984 | 32% |
| mro | 1068 | 2640 | 40% |
| dicts | 1447 | 3469 | 42% |
| lists | 10747 | 19961 | 54% |
| imports | 1900 | 3024 | 63% |
| classes | 4087 | 5600 | 73% |
| decorators | 1115 | 1511 | 74% |
| returns | 2607 | 3453 | 75% |
| assignments | 27042 | 33673 | 80% |
| kwargs | 152 | 161 | 94% |
| direct_calls | 154 | 161 | 96% |
| args | 321 | 332 | 97% |
| functions | 480 | 491 | 98% |
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
| `["bool"]` | `["any"]` | 76 |
| `["float"]` | `["any"]` | 76 |
| `["int"]` | `["any"]` | 76 |
| `["str"]` | `["any"]` | 76 |
| `["dict"]` | `["any"]` | 67 |
| `["list"]` | `["any"]` | 67 |
| `["tuple"]` | `["any"]` | 67 |
| `["str"]` | `["float", "str"]` | 59 |
| `["str"]` | `["int", "str"]` | 59 |
| `["int"]` | `["int", "list"]` | 58 |
| `["int"]` | `["dict", "int"]` | 54 |
| `["int"]` | `["dict", "list"]` | 54 |
| `["int"]` | `["dict", "tuple"]` | 54 |
| `["int"]` | `["int", "tuple"]` | 54 |
| _(+347 more)_ | | 6401 |
| **Total TYPE_MISS** | | **9596** |

## Translation errors (7 snippets)

Grouped by error class + leading detail; snippets that translated cleanly but produced no GT-matching wires are NOT in this list.

| Error class | Detail | Count |
| --- | --- | ---: |
| `CycleError` | `import cycle detected among modules: ['main', 'nested_init']` | 7 |

### Snippet lists per error class

**`CycleError: import cycle detected among modules: ['main', 'nested_init']`** (7)

- `imports/init_import_1_1_int`
- `imports/init_import_1_2_float`
- `imports/init_import_1_3_str`
- `imports/init_import_1_4_bool`
- `imports/init_import_1_5_list`
- `imports/init_import_1_6_dict`
- `imports/init_import_1_7_tuple`
