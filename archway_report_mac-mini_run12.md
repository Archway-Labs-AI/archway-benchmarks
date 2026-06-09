# Run #12 — typeevalpy · archway-translation+archway-analysis

_Created 2026-06-09T21:13:20+00:00_ · _micro — post adapter-fix (engine loop/nightly-20260609-0826)_

- **Exact:** 686 / 850 (80.7%)
- **Files processed:** 152 / 153
- **Files sound:** 95 / 153
- **Files complete:** 101 / 153
- **Annotation precision:** 0.839
- **Annotation recall:** 0.807

## Outcome breakdown

| Kind | EXACT | TYPE_MISS | LOCATION_MISS | Total |
| --- | ---: | ---: | ---: | ---: |
| parameter | 92 | 3 | 0 | 95 |
| return | 208 | 22 | 0 | 230 |
| variable | 386 | 107 | 32 | 525 |

## Per-category accuracy (worst first)

| Category | Exact | Total | Rate |
| --- | ---: | ---: | ---: |
| external | 2 | 16 | 12% |
| generators | 23 | 70 | 33% |
| dynamic | 3 | 9 | 33% |
| exceptions | 1 | 2 | 50% |
| builtins | 41 | 68 | 60% |
| lists | 43 | 60 | 72% |
| returns | 35 | 43 | 81% |
| dicts | 89 | 107 | 83% |
| imports | 21 | 25 | 84% |
| mro | 29 | 34 | 85% |
| assignments | 76 | 82 | 93% |
| classes | 115 | 122 | 94% |
| args | 41 | 43 | 95% |
| kwargs | 21 | 22 | 95% |
| decorators | 51 | 52 | 98% |
| direct_calls | 24 | 24 | 100% |
| functions | 37 | 37 | 100% |
| lambdas | 34 | 34 | 100% |

## TYPE_MISS patterns (top by count)

| Expected | Predicted | Count |
| --- | --- | ---: |
| `["int"]` | `["TypeError"]` | 16 |
| `["str"]` | `["int", "str"]` | 7 |
| `["int"]` | `["any"]` | 6 |
| `["int"]` | `["int", "str"]` | 5 |
| `["str"]` | `["any"]` | 5 |
| `["str"]` | `["dict"]` | 5 |
| `["float"]` | `["float", "int", "str"]` | 4 |
| `["int"]` | `[]` | 4 |
| `["Cls"]` | `[]` | 3 |
| `["Nonetype"]` | `["any"]` | 3 |
| `["float"]` | `["any"]` | 3 |
| `["generator"]` | `["list"]` | 3 |
| `["int", "str"]` | `["str"]` | 3 |
| `["int"]` | `["float", "int", "str"]` | 3 |
| `["str"]` | `["float", "int", "str"]` | 3 |
| `["Point"]` | `["any"]` | 2 |
| `["callable"]` | `["TypeError"]` | 2 |
| `["callable"]` | `["any"]` | 2 |
| `["callable"]` | `["callable", "int"]` | 2 |
| `["int", "str"]` | `["int"]` | 2 |
| `["int"]` | `["int", "list"]` | 2 |
| `["int"]` | `["tuple"]` | 2 |
| `["str"]` | `["NameError"]` | 2 |
| `["str"]` | `["tuple"]` | 2 |
| `["typeevalpy_external_module.ext.Cls"]` | `["any"]` | 2 |
| `["A.B"]` | `["B"]` | 1 |
| `["MyClass"]` | `["NewClass"]` | 1 |
| `["bool"]` | `["TypeError", "bool"]` | 1 |
| `["callable"]` | `["TypeError", "callable"]` | 1 |
| `["callable"]` | `["callable", "str"]` | 1 |
| _(+34 more)_ | | 34 |
| **Total TYPE_MISS** | | **132** |

## Translation errors (1 snippets)

Grouped by error class + leading detail; snippets that translated cleanly but produced no GT-matching wires are NOT in this list.

| Error class | Detail | Count |
| --- | --- | ---: |
| `CycleError` | `import cycle detected among modules: ['main', 'nested_init']` | 1 |

### Snippet lists per error class

**`CycleError: import cycle detected among modules: ['main', 'nested_init']`** (1)

- `imports/init_import`
