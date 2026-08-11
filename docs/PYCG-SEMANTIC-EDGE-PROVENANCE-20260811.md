# PyCG semantic edge provenance — 2026-08-11

## Purpose

PyCG's expected graphs omit many source-visible builtin, protocol, and
external-object calls.  Raw scorer precision therefore cannot establish the
successor's semantic precision.  Conversely, dismissing every raw extra would
hide real errors such as fabricated external-result namespace chains.

Successor runs now retain contextual edge evidence and all display-projection
lineage in `analysis_evidence`.  This allows each raw extra to be reviewed at
its actual diagram callsite without rerunning an isolated edge analysis.

## Schema additions

Each successful case records:

- `semantic_call_edge_evidence`: contextual semantic edge records;
- `semantic_call_edge_evidence_count`;
- `semantic_direct_edge_count`;
- `pycg_projection_lineage`: one record for every retained, omitted, or
  synthetic-caller-attributed direct edge;
- `pycg_projection_lineage_count`;
- `pycg_projected_edge_count`.

These fields are evidence only.  The scored edge set is unchanged.

## End-to-end checks

The retained micro artifact is
`/private/tmp/archway-edge-provenance-micro/result.json`.  It covers all 119
cases and all 255 predictions.  Every prediction has direct evidence or
projection lineage.  The result remains 254/264 with the same one raw extra
and ten adjudicated expected-graph disagreements.

The focused macro artifact is
`/private/tmp/archway-edge-provenance-asciinema/result.json`.  It remains 228
raw true positives, 44 raw extras, and 112 false negatives.

All 44 Asciinema extras were reviewed at their retained source spans:

| semantic category | edges | disposition |
| --- | ---: | --- |
| direct builtin/file/container/string calls | 18 | semantically required |
| direct reviewed external-object calls | 20 | semantically required |
| local context-manager enter/exit calls | 6 | semantically required |

Examples include `str.upper` at `asciinema.__main__:29`,
`Request.add_header` at `asciinema.asciicast:47`, `Response.geturl` at line 50,
`ConfigParser.getboolean` at the corresponding configuration property spans,
and local `raw.__enter__/__exit__` calls at their `with` statements.  The
repeated contextual records for some edges represent distinct admitted
contexts at the same source callsite, not additional scored edges.

Therefore this Asciinema checkpoint has 100% adjudicated semantic precision
for its 272 predicted edges even though raw PyCG precision is 83.82%.  This is
one framework result, not yet proof of the five-framework 99% aggregate goal.
