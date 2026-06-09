# Run #11 — typeevalpy_autogen · archway-translation+archway-analysis

_Created 2026-06-09T21:07:08+00:00_ · _autogen — adapter-fix verify (engine loop/nightly-20260609-0826)_

- **Exact:** 53842 / 77268 (69.7%)
- **Files processed:** 5439 / 5453
- **Files sound:** 1364 / 5453
- **Files complete:** 1524 / 5453
- **Annotation precision:** 0.829
- **Annotation recall:** 0.697

## Outcome breakdown

| Kind | EXACT | TYPE_MISS | LOCATION_MISS | Total |
| --- | ---: | ---: | ---: | ---: |
| parameter | 795 | 89 | 12 | 896 |
| return | 16037 | 1860 | 101 | 17998 |
| variable | 37010 | 9189 | 12175 | 58374 |

## Per-category accuracy (worst first)

| Category | Exact | Total | Rate |
| --- | ---: | ---: | ---: |
| dynamic | 21 | 108 | 19% |
| generators | 65 | 259 | 25% |
| builtins | 626 | 1984 | 32% |
| dicts | 1503 | 3469 | 43% |
| lists | 10747 | 19961 | 54% |
| mro | 1487 | 2640 | 56% |
| imports | 1900 | 3024 | 63% |
| returns | 2607 | 3453 | 75% |
| decorators | 1157 | 1511 | 77% |
| assignments | 27042 | 33673 | 80% |
| classes | 5137 | 5600 | 92% |
| kwargs | 152 | 161 | 94% |
| args | 321 | 332 | 97% |
| functions | 480 | 491 | 98% |
| lambdas | 436 | 441 | 99% |
| direct_calls | 161 | 161 | 100% |

## TYPE_MISS patterns (top by count)

| Expected | Predicted | Count |
| --- | --- | ---: |
| `["callable"]` | `["callable", "str"]` | 840 |
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
| `["bool"]` | `[]` | 85 |
| `["float"]` | `[]` | 85 |
| `["int"]` | `[]` | 85 |
| `["str"]` | `[]` | 85 |
| `["callable"]` | `["callable", "int"]` | 84 |
| `["dict"]` | `[]` | 84 |
| `["list"]` | `[]` | 84 |
| `["tuple"]` | `[]` | 84 |
| `["bool"]` | `["any"]` | 76 |
| `["float"]` | `["any"]` | 76 |
| `["int"]` | `["any"]` | 76 |
| `["str"]` | `["any"]` | 76 |
| `["dict"]` | `["any"]` | 67 |
| `["list"]` | `["any"]` | 67 |
| _(+360 more)_ | | 6970 |
| **Total TYPE_MISS** | | **11138** |

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
