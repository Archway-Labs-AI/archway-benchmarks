# PyCG residual audit contract — 2026-08-12

## Boundary

The audit keeps three products distinct:

1. Archway analysis produces diagram-derived semantic call edges.
2. The PyCG adapter translates semantic identities into PyCG display
   conventions and records every projection decision.
3. The scorer compares the adapted edge set with immutable benchmark
   expectations.

Neither automated clustering nor benchmark agreement is a semantic
adjudication. The adapter may normalize representation; it may not infer a
call that analysis did not establish or erase a call solely to improve a
score.

## Artifacts

`pycg_residual_audit` builds
`archway.pycg.residual-audit.v1`. It inventories both unique false-positive
and false-negative edges, preserves the raw score, links retained callsite
evidence, and assigns diagnostic clusters.

Human or agent review is recorded separately in
`archway.pycg.residual-adjudications.v1`. Every reviewed entry requires a
stable residual ID, controlled disposition, reviewer, rationale, and evidence
references. Stale entries are rejected when applied to a run.

The audit reports unique residuals separately from scored occurrences. PyCG
ground truth can contain duplicate expected-edge occurrences: the retained
five-project checkpoint has 720 unique residual edges but 721 scored residual
occurrences.

## Controlled dispositions

- `semantically_valid_extra`
- `benchmark_defect_or_omission`
- `adapter_representation_mismatch`
- `archway_precision_gap`
- `archway_unsoundness`
- `translation_or_ir_defect`
- `unsupported_semantics`
- `inconclusive`

The distinction between a precision gap and unsoundness is directional here:
a missing semantically required edge is a precision/capability gap; a
fabricated or impossible edge is an unsound over-approximation. Review may
instead identify translation loss or unsupported semantics as the root cause.

## First inventory

The retained full checkpoint contains 330 unique raw extras and 390 unique
missing edges. Automated evidence linkage gives:

| diagnostic cluster | edges |
| --- | ---: |
| builtin/runtime extra | 131 |
| external dependency extra | 131 |
| implicit protocol extra | 34 |
| project/resolved-object extra | 34 |
| missing caller analysis | 38 |
| missing callsite or target | 184 |
| wrong/missing target at observed lexical callsite | 159 |
| projection/adapter candidate | 9 |

All 330 extras have retained semantic evidence. The nine initial adapter
candidates are exact semantic edges that the adapter subsequently records as
`omit_synthetic_target`. Source excerpts confirm direct calls such as
`iter(arg_strings)` and `dict.update(...)`; they are reviewed in
`adjudications/pycg-macro-20260812-adapter.json`.

An attempted repair based only on the callsite IR operation recovered those
nine candidates (six in Autojump) but exposed 32 additional implicit Autojump
iteration helpers. Lowered implicit helpers can also occur in `evaluate`
boxes. A safe adapter repair therefore requires stronger diagram provenance
for explicit versus lowering-generated calls; source-text heuristics are not
acceptable analysis or projection inputs.
