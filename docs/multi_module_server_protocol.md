# Multi-module snippets — server protocol options

Most of the 37 remaining import-blocked TypeEvalPy micro snippets are **cross-module sibling imports** — `main.py` imports a `.py` file sitting next door (or in a subpackage). The analysis server today handles only single files; this doc lays out what the benchmark needs to send and what the server needs to accept.

## What the benchmark has on disk

Each multi-module snippet is a self-contained directory under `vendor/TypeEvalPy/micro-benchmark/python_features/<category>/<snippet>/`. The layouts that occur:

### Pattern A — flat sibling (most common, ~15 snippets)

```
imports/simple_import/
├── main.py            # `import to_import; a = to_import.func()`
├── main_gt.json
└── to_import.py       # `def func(): return 42`
```

### Pattern B — nested package + `__init__.py` (~6 snippets)

```
imports/relative_import/
├── __init__.py
├── main.py            # `import nested.to_import`
├── main_gt.json
├── to_import.py
└── nested/
    ├── __init__.py
    ├── to_import.py   # `from . import to_import2` — relative import
    └── to_import2.py
```

### Pattern C — submodule package (~3 snippets)

```
imports/submodule_import/
├── main.py            # `import to_import_sub.to_import_sub`
├── main_gt.json
└── to_import_sub/
    ├── __init__.py    # `def func(): return 42.5`  — also defines top-level names
    └── to_import_sub.py   # `def func(): return 42`
```

### Pattern D — relative imports between siblings (~3 snippets)

```
imports/parent_import/
├── __init__.py
├── main.py            # `from nested import to_import`
├── main_gt.json
├── nested/
│   ├── __init__.py
│   └── to_import.py   # `import to_import2`  — relative-without-dot
└── to_import2.py
```

### GT keys all point at main.py

Every ground-truth entry has `"file": "main.py"`. The benchmark only ever asks for predictions on `main.py`'s annotations; the sibling files are needed for *value flow* but the GT doesn't query them directly. So **the analyzer only has to surface `main.py`'s bindings correctly** — it just needs to have analyzed the sibling modules during that work.

## Current server protocol (single-file)

Two endpoints today (`sd_core/analysis_server.py`):

```
POST /types?name=<name>       → body is Python source, analyze that one source
GET  /types?module=<rel-path> → resolve under --repo-root, analyze that one file
```

The benchmark currently uses `POST` with the entire source as the body, because that:
- Doesn't require the server's `--repo-root` to point at the snippet's directory
- Keeps a single global `--repo-root` (`vendor/TypeEvalPy/micro-benchmark`) across the whole run

Neither endpoint exposes sibling files to the analyzer. So even if the analyzer learned about `import` semantics, it can't reach into `to_import.py` because nothing has told it where that file is.

## What needs to change

The server has to:
1. Know **where the snippet directory is** for each request
2. Know **which directory to treat as the package root** for import resolution
3. Be able to read sibling files from disk during analysis (or have them passed in-band)
4. Support **relative imports** (`from . import x`, `from .. import y`) — which only makes sense given a package context

The benchmark side has to:
1. Identify each snippet's root directory (`vendor/TypeEvalPy/micro-benchmark/python_features/<category>/<snippet>/`)
2. Communicate that root to the server per request

## Endpoint design options

### Option 1 — Per-request `root` parameter on the existing `GET /types?module=` endpoint

```
GET /types?module=main.py&root=/abs/path/to/snippet/dir
```

Server semantics:
- `root` overrides `Config.repo_root` for this one request
- Resolves `module` relative to `root` (so `main.py` is `<root>/main.py`)
- Import resolution uses `root` as the package's filesystem root
- Relative imports (`from . import x`) resolve against the current module's directory within `root`

**Pros:**
- Minimal protocol change — one extra query param
- Disk-based, no transport overhead for the source itself
- Server already does file reads; just generalize the root

**Cons:**
- Server must be able to read the benchmark's directory (which it can — running on the same machine in our case)
- Couples the server to filesystem layout; not great if we ever want to send synthetic snippets

This is the cheapest path for our setup.

### Option 2 — Multi-file POST body

```
POST /types
Content-Type: application/json

{
  "entry": "main.py",
  "files": {
    "main.py":           "<source of main.py>",
    "to_import.py":      "<source of to_import.py>",
    "nested/__init__.py":"",
    "nested/to_import.py":"<source>"
  },
  "package_root": ""
}
```

Server semantics:
- Build an in-memory module map from `files`
- Analyze `entry` and walk imports through the in-memory map
- Relative imports resolve based on each file's path within the map

**Pros:**
- No disk dependency — server can be remote, sandboxed, anywhere
- Synthetic snippets work out of the box
- Self-describing payload

**Cons:**
- Bigger request bodies (rarely an issue for benchmark snippets, but matters at scale)
- Server needs an in-memory virtual-filesystem for import resolution
- More moving parts

### Option 3 — Tarball upload

```
POST /types?entry=main.py
Content-Type: application/x-tar

<tarball of the snippet directory>
```

Server unpacks to a temp dir, analyzes, returns response.

**Pros:**
- Preserves the on-disk shape exactly
- Works for arbitrary directory structures (binary files, large suites)

**Cons:**
- Most complex of the three
- Temp-dir lifecycle, disk usage, cleanup
- Probably overkill for a benchmark where every snippet is small Python

## Recommendation

**Go with Option 1.** For our local-server benchmark workflow it's the smallest change that unblocks the work:

- Benchmark side: change `ArchwayAnalysisEngine` to send `GET /types?module=main.py&root=<snippet_dir>` instead of `POST /types?name=snippet` with the source body
- Server side: accept the `root` query param; use it as the per-request package root; pass it down to the analyzer

If you later want to send synthetic or cross-machine snippets, Option 2 can layer on top — the JSON projection contract doesn't change.

## What the analyzer side needs to handle

Regardless of which transport option lands:

### Module resolution within a package

Given an `import x` from a file at `<root>/main.py`:

1. Look for `<root>/x.py`
2. Look for `<root>/x/__init__.py`
3. (If neither) fall back to site-packages or fail

Given `import a.b.c`: walk down `<root>/a/b/c.py` or `<root>/a/b/c/__init__.py`, treating each `__init__.py` as defining the package's namespace.

### Relative imports

`from . import foo` and `from .sibling import bar` only make sense if the current module is inside a package (i.e., its directory contains an `__init__.py` or is otherwise a package root).

Reference: each module has a "package" — the dotted path from the package root down to that file's directory. Relative imports walk up that path.

- Inside `<root>/nested/to_import.py` (where `<root>` and `<root>/nested/` both have `__init__.py`), `from . import to_import2` means `<root>/nested/to_import2.py`.
- `from .. import x` means `<root>/x.py` or `<root>/x/__init__.py`.

### Recursive analysis

`main.py` imports `to_import.py`; `to_import.py` imports `to_import2.py`. The analyzer needs to analyze all three (in dependency order, with cycle detection) and surface every module's name → element mapping. When `main.py`'s `import to_import` runs, the analyzer binds `to_import` in `main.py`'s scope to a module-element whose attributes are the names defined in `to_import.py`.

### `__init__.py` semantics

When `import to_import_sub.to_import_sub` runs and `to_import_sub/__init__.py` exists:

- Both packages are loaded: `to_import_sub` (from the `__init__.py`) and `to_import_sub.to_import_sub` (from the nested file)
- `main.py`'s scope gets `to_import_sub` bound to a module element whose attributes include everything `__init__.py` defines PLUS `to_import_sub` (the nested module)
- So `to_import_sub.func()` resolves to `__init__.py`'s `func`, and `to_import_sub.to_import_sub.func()` resolves to the nested module's `func`

This is the pattern in `imports/submodule_import` — both `a = to_import_sub.to_import_sub.func()` (returns int) and `b = to_import_sub.func()` (returns float) need to resolve to different `func` definitions.

## What the benchmark adapter will need to change

Tiny changes if we pick Option 1:

- `ArchwayAnalysisEngine.analyze` — switch from POST-source to GET-module
- Each snippet's `file_path` (already populated in `Snippet`) tells us the snippet's directory; that's the `root`
- The response shape and contents don't change

No `archway_adapter.py` changes needed (the `FinalizedAnalysis` shape stays the same — we just expect more bindings to be populated for previously-failing snippets).

## Out of scope for this work

- **Stdlib imports** (`functools`, `itertools`, `abc`, `collections`) — already deferred per earlier discussion. Touch ~4 snippets and would require hand-modeling specific stdlib signatures.
- **`typeevalpy_external_module`** — the 8 `external/*` snippets. This is a pip-installed package; supporting it means the analyzer also needs to look in site-packages. Could be a follow-up once sibling-file resolution works, by extending the resolution algorithm to also walk a configured set of "external" roots.
