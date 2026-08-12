# PyCG Full Semantic Residual Audit — 2026-08-12

## Scope

This audit adjudicates every residual in the retained full successor run:

`/Volumes/LaCie/Archway/benchmark-artifacts/pycg-runs/successor-20260812-full/result.json`

The raw scorer result remains immutable. Adjudications are separate, exact-ID manifests under `adjudications/`; they do not alter Archway analysis or silently normalize benchmark answers.

The scorer contains 721 residual occurrences representing 720 unique residuals. All 720 unique residuals have a reviewed disposition; none remain pending.

## Raw score

- True positives: 1,707 unique / 1,709 recall occurrences
- False positives: 330
- False negatives: 391 occurrences / 390 unique
- Precision: 0.837997
- Recall: 0.813810
- F1: 0.825726

These raw metrics substantially understate semantic precision because PyCG omits many real operations that Archway reports. They also mix genuine analysis gaps with incompatible target naming and incorrect expected edges.

## Reviewed result

| Disposition | Unique residuals |
| --- | ---: |
| Semantically valid Archway extra | 304 |
| Archway precision gap | 249 |
| Archway unsoundness | 19 |
| Adapter representation mismatch | 74 |
| Benchmark defect or omission | 74 |
| Pending | 0 |

### By case

| Case | Valid extras | Precision gaps | Unsound | Adapter | Benchmark | Pending |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Autojump | 64 | 100 | 1 | 20 | 8 | 0 |
| Fabric | 89 | 57 | 11 | 39 | 11 | 0 |
| Asciinema | 65 | 58 | 0 | 15 | 16 | 0 |
| Face Classification | 44 | 1 | 0 | 0 | 15 | 0 |
| Sublist3r | 42 | 33 | 7 | 0 | 24 | 0 |

## Principal findings

### 1. Receiver-type pollution is the highest-severity correctness defect

Eighteen of the nineteen unsound edges share a concrete pattern:

- `Queue.get` or `requests.Session.get` becomes `dict.get` in Sublist3r.
- `Connection.get` or SFTP `get` becomes `dict.get` in Fabric.
- thread `join` or `py.path.join` becomes `str.join` in Fabric.

These are not scoring conventions. They are wrong semantic edges paired with missed correct targets and indicate reduced-product receiver information is being widened or conflated before attribute/call resolution.

The remaining unsound edge attributes a generator-expression `isupper` call to the enclosing function instead of the generator callable boundary.

### 2. Most scored false positives are semantically useful

304 residuals are real calls omitted by PyCG: builtin/container operations, precise receiver methods, context-manager protocol calls, property evaluation, external library calls, and project calls. Removing these edges to improve raw precision would make Archway less truthful and less useful.

### 3. Missing call flow remains substantial

249 residuals are genuine coverage gaps. Important recurring families include:

- nested functions, lambdas, comprehensions, and callbacks;
- constructors and dynamic callable dispatch;
- inherited and external receiver methods;
- alternate reachable implementation routes;
- thread, queue, synchronization, and context-manager flows;
- cross-module command, formatter, and framework dispatch.

These gaps should guide minimal regression examples and architectural repairs, not benchmark-specific edge injection.

### 4. The scorer boundary needs explicit semantic normalization

74 residuals represent the same call with incompatible names, including precise receiver methods versus module aliases, vendored versus public module paths, constructor boundaries, socket class capitalization, standard streams/environment objects, and compatibility aliases.

Normalization belongs in a transparent PyCG scoring adapter. It must never change the engine's canonical semantic edge.

### 5. PyCG expected data contains material noise

74 residuals are impossible, misspelled, source-inconsistent, or omitted expected operations. Examples include nonexistent methods such as `Event.join`, invalid receiver methods, misspelled targets, coarse targets contradicted by the source, and omitted real builtin/protocol calls.

The benchmark remains useful, but raw precision and recall cannot serve as semantic authority.

## Repair order

1. Pin minimal receiver-pollution regressions for `get` and `join`, then repair reduced-product receiver propagation.
2. Pin and repair synthetic callable-boundary attribution for generator/comprehension bodies.
3. Cluster the 249 precision gaps by missing mechanism and address shared analysis causes, beginning with nested callable flow and dynamic receiver dispatch.
4. Implement an explicit, testable PyCG scoring normalization layer for the 74 representation mismatches.
5. Preserve reviewed benchmark defects as audit evidence; do not encode them into analysis behavior.
6. Re-run the full benchmark and compare both immutable raw scores and reviewed semantic dispositions.

## Reproduction

Generate the base inventory with `archway_benchmarks.pycg_residual_audit`, supplying every `pycg-macro-20260812-*.json` adjudication manifest. The generated reviewed inventory used during this audit is `/tmp/pycg-full-reviewed-audit.json`; it is reproducible rather than committed because it duplicates the retained run and exact manifests.
