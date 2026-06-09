# Run #42 — typeevalpy · archway-translation+archway-analysis

_Created 2026-06-05T13:46:36+00:00_ · _loop worktree_

- **Exact:** 598 / 850 (70.4%)
- **Files processed:** 152 / 153
- **Files sound:** 62 / 153
- **Files complete:** 106 / 153
- **Annotation precision:** 0.840
- **Annotation recall:** 0.704

## Outcome breakdown

| Kind | EXACT | TYPE_MISS | LOCATION_MISS | Total |
| --- | ---: | ---: | ---: | ---: |
| parameter | 92 | 3 | 0 | 95 |
| return | 145 | 5 | 80 | 230 |
| variable | 361 | 106 | 58 | 525 |

## Per-category accuracy (worst first)

| Category | Exact | Total | Rate |
| --- | ---: | ---: | ---: |
| external | 2 | 16 | 12% |
| generators | 17 | 70 | 24% |
| dynamic | 3 | 9 | 33% |
| mro | 14 | 34 | 41% |
| exceptions | 1 | 2 | 50% |
| classes | 67 | 122 | 55% |
| builtins | 41 | 68 | 60% |
| lists | 43 | 60 | 72% |
| returns | 33 | 43 | 77% |
| decorators | 40 | 52 | 77% |
| dicts | 86 | 107 | 80% |
| imports | 21 | 25 | 84% |
| assignments | 76 | 82 | 93% |
| functions | 35 | 37 | 95% |
| args | 41 | 43 | 95% |
| kwargs | 21 | 22 | 95% |
| direct_calls | 23 | 24 | 96% |
| lambdas | 34 | 34 | 100% |

## TYPE_MISS patterns (top by count)

| Expected | Predicted | Count |
| --- | --- | ---: |
| `["int"]` | `["TypeError"]` | 15 |
| `["str"]` | `["int", "str"]` | 7 |
| `["int"]` | `["any"]` | 5 |
| `["int"]` | `["int", "str"]` | 5 |
| `["str"]` | `["any"]` | 5 |
| `["str"]` | `["dict"]` | 5 |
| `["float"]` | `["float", "int", "str"]` | 4 |
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
| `["str"]` | `["NameError"]` | 2 |
| `["str"]` | `["tuple"]` | 2 |
| `["typeevalpy_external_module.ext.Cls"]` | `["any"]` | 2 |
| `["A.B"]` | `["B"]` | 1 |
| `["MyClass"]` | `["NewClass"]` | 1 |
| `["bool"]` | `["TypeError", "bool"]` | 1 |
| `["callable"]` | `["TypeError", "callable"]` | 1 |
| `["callable"]` | `["dict"]` | 1 |
| `["code"]` | `["TypeError"]` | 1 |
| `["float"]` | `["float", "int"]` | 1 |
| `["int"]` | `["TypeError", "int", "str"]` | 1 |
| `["int"]` | `["TypeError", "int"]` | 1 |
| _(+27 more)_ | | 27 |
| **Total TYPE_MISS** | | **114** |

## Translation errors (1 snippets)

Grouped by error class + leading detail; snippets that translated cleanly but produced no GT-matching wires are NOT in this list.

| Error class | Detail | Count |
| --- | --- | ---: |
| `CycleError` | `import cycle detected among modules: ['main', 'nested_init']` | 1 |

### Snippet lists per error class

**`CycleError: import cycle detected among modules: ['main', 'nested_init']`** (1)

- `imports/init_import`
