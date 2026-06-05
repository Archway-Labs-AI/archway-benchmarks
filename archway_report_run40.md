# Run #40 — typeevalpy · archway-translation+archway-analysis

_Created 2026-06-05T06:59:14+00:00_ · _loop worktree_

- **Exact:** 585 / 850 (68.8%)
- **Files processed:** 150 / 153
- **Files sound:** 58 / 153
- **Files complete:** 102 / 153
- **Annotation precision:** 0.831
- **Annotation recall:** 0.688

## Outcome breakdown

| Kind | EXACT | TYPE_MISS | LOCATION_MISS | Total |
| --- | ---: | ---: | ---: | ---: |
| parameter | 90 | 3 | 2 | 95 |
| return | 145 | 5 | 80 | 230 |
| variable | 350 | 111 | 64 | 525 |

## Per-category accuracy (worst first)

| Category | Exact | Total | Rate |
| --- | ---: | ---: | ---: |
| external | 2 | 16 | 12% |
| generators | 17 | 70 | 24% |
| dynamic | 3 | 9 | 33% |
| mro | 13 | 34 | 38% |
| exceptions | 1 | 2 | 50% |
| classes | 65 | 122 | 53% |
| builtins | 41 | 68 | 60% |
| imports | 17 | 25 | 68% |
| lists | 43 | 60 | 72% |
| returns | 33 | 43 | 77% |
| decorators | 40 | 52 | 77% |
| dicts | 86 | 107 | 80% |
| functions | 32 | 37 | 86% |
| assignments | 73 | 82 | 89% |
| args | 41 | 43 | 95% |
| kwargs | 21 | 22 | 95% |
| direct_calls | 23 | 24 | 96% |
| lambdas | 34 | 34 | 100% |

## TYPE_MISS patterns (top by count)

| Expected | Predicted | Count |
| --- | --- | ---: |
| `["int"]` | `["TypeError"]` | 16 |
| `["str"]` | `["any"]` | 7 |
| `["str"]` | `["int", "str"]` | 7 |
| `["int"]` | `["any"]` | 5 |
| `["int"]` | `["int", "str"]` | 5 |
| `["float"]` | `["float", "int", "str"]` | 4 |
| `["str"]` | `["dict"]` | 4 |
| `["Nonetype"]` | `["any"]` | 3 |
| `["generator"]` | `["list"]` | 3 |
| `["int"]` | `["float", "int", "str"]` | 3 |
| `["str"]` | `["float", "int", "str"]` | 3 |
| `["Point"]` | `["any"]` | 2 |
| `["callable"]` | `["TypeError"]` | 2 |
| `["callable"]` | `["any"]` | 2 |
| `["callable"]` | `["callable", "int"]` | 2 |
| `["float"]` | `["any"]` | 2 |
| `["int"]` | `["int", "list"]` | 2 |
| `["int"]` | `["tuple"]` | 2 |
| `["set"]` | `["TypeError"]` | 2 |
| `["str"]` | `["NameError"]` | 2 |
| `["str"]` | `["TypeError"]` | 2 |
| `["str"]` | `["tuple"]` | 2 |
| `["typeevalpy_external_module.ext.Cls"]` | `["any"]` | 2 |
| `["A.B"]` | `["B"]` | 1 |
| `["MyClass"]` | `["NewClass"]` | 1 |
| `["bool"]` | `["TypeError", "bool"]` | 1 |
| `["callable"]` | `["TypeError", "callable"]` | 1 |
| `["callable"]` | `["dict"]` | 1 |
| `["code"]` | `["TypeError"]` | 1 |
| `["float"]` | `["float", "int"]` | 1 |
| _(+28 more)_ | | 28 |
| **Total TYPE_MISS** | | **119** |

## Translation errors (3 snippets)

Grouped by error class + leading detail; snippets that translated cleanly but produced no GT-matching wires are NOT in this list.

| Error class | Detail | Count |
| --- | --- | ---: |
| `NotImplementedError` | ``from x import *`` | 2 |
| `CycleError` | `import cycle detected among modules: ['main', 'nested_init']` | 1 |

### Snippet lists per error class

**`NotImplementedError: `from x import *``** (2)

- `imports/import_all`
- `imports/submodule_import_all`

**`CycleError: import cycle detected among modules: ['main', 'nested_init']`** (1)

- `imports/init_import`
