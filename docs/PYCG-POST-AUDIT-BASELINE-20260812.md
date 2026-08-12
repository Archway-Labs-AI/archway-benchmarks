# PyCG Post-Audit Baseline — 2026-08-12

## Purpose

This run validates the receiver-candidate soundness repair and transparent PyCG scoring normalization. Detailed tracing was disabled.

Artifact:

`/Volumes/LaCie/Archway/benchmark-artifacts/pycg-runs/successor-20260812-post-audit/result.json`

## Result

| Metric | Audited predecessor | Post-audit baseline |
| --- | ---: | ---: |
| Precision | 0.837997 | 0.882670 |
| Recall | 0.813810 | 0.781905 |
| F1 | 0.825726 | 0.829237 |
| Predicted edges | 2,037 | 1,640 |
| False positives | 330 | 218 |
| False negatives | 391 | 458 |

Total elapsed time was 289.1 seconds. All five cases completed within the 300-second per-case bound; Sublist3r took 113.6 seconds.

## Interpretation

The 19 previously adjudicated unsound edges are absent, including the known `dict.get`, `str.join`, and generator caller-attribution failures.

Receiver capability candidates are still retained and explicitly inspectable, but they no longer:

- seed uninvoked callable parameter types;
- refine downstream result facts through builtin summaries; or
- appear in the default semantic call graph.

Recall fell because earlier runs counted heuristic receiver guesses as semantic edges. This is an intentional correction, not a precision regression. The resulting additional misses belong in the precision-gap backlog and must be recovered through real type, callable-flow, or receiver evidence.

The scoring adapter performed 36 unique explicit normalizations in this new run. The canonical semantic edges remain available in analysis evidence; only their benchmark-facing spellings changed.

## Per-case raw score

| Case | Precision | Recall | F1 | Seconds |
| --- | ---: | ---: | ---: | ---: |
| Autojump | 0.875817 | 0.750466 | 0.808310 | 77.6 |
| Fabric | 0.822430 | 0.692913 | 0.752137 | 27.5 |
| Asciinema | 0.838926 | 0.736070 | 0.784140 | 38.9 |
| Face Classification | 0.916484 | 0.958621 | 0.937079 | 31.5 |
| Sublist3r | 0.944615 | 0.756158 | 0.839945 | 113.6 |

## Next action

Do not restore candidate promotion to recover recall. Future precision work should begin with minimal diagram-only examples from the mechanism-oriented backlog and introduce evidence that composes through the reduced product.
