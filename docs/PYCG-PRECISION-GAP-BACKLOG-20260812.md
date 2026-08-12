# PyCG Precision-Gap Backlog — 2026-08-12

This is the non-priority repair backlog derived from the completed semantic audit. Exact residual membership remains authoritative in the adjudication manifests; this document records shared mechanisms so later work targets architectural causes instead of individual benchmark edges.

## Current population

249 unique residuals are classified as `archway_precision_gap`:

- Autojump: 100
- Fabric: 57
- Asciinema: 58
- Face Classification: 1
- Sublist3r: 33

## Mechanism-oriented clusters

### Nested callable and synthetic-boundary flow

Missing calls inside lambdas, comprehensions, generator bodies, and locally defined helpers, plus calls between those boundaries. This is a high-leverage future target because one repair can recover many edges while also improving caller attribution.

### Dynamic receiver and inherited method dispatch

Calls whose receiver comes through a parameter, property, external result, inheritance, or a framework-configured object. This cluster should be revisited after the receiver-candidate soundness repair has established a clean evidence boundary.

### Constructor and callable-object flow

Missing class constructors, dynamically selected action classes, `__call__` dispatch, and constructor aliases. Repairs should operate through ordinary callable-value and class facts rather than constructor-name special cases.

### Callback and framework dispatch

Callbacks passed through parser actions, worker/thread wrappers, command objects, notifier/writer objects, and framework extension points. This is closely related to the future large-framework call-graph work.

### External and compatibility-route flow

Real dependency methods and Python-version/platform alternatives that remain possible on analyzed routes. Route feasibility should eventually prune impossible alternatives; until then, reachable alternatives should remain represented without fabricating certainty.

### Protocol and concurrency flow

Queue, thread, synchronization, iterator, context-manager, socket, and file-like operations. Some misses may fall out naturally from better receiver and callback propagation.

## Opportunistic repairs

Do not optimize isolated benchmark edges. A precision repair is eligible before this backlog becomes a priority only when it:

1. falls directly out of a soundness or scorer-boundary repair;
2. has a small diagram-only regression demonstrating a shared mechanism;
3. does not introduce source/AST analysis or benchmark-specific engine behavior; and
4. improves the reduced-product information flow generally.

## Evidence policy

- Exact residuals remain in `adjudications/pycg-macro-20260812-*.json`.
- Valid extras and benchmark defects require no engine suppression.
- Adapter mismatches belong exclusively to the transparent PyCG scoring projection.
- Reclassification requires new semantic evidence and an updated exact-ID manifest.
