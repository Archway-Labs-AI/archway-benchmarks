# TypyBench successor focused baseline — 2026-08-13

This is the first focused score after extracting successor invocation/catalog/
deferred-result responsibilities and adding compositional `bytes` plus
structured external atomic-result summaries. It is a development checkpoint,
not evidence for the full 50-repository acceptance gate.

## Engine identity

- Branch: `workbench/diagram-analysis-rebuild`
- Commit: `133842aa` (`Compose structured atomic call results`)
- Analysis surface: translated diagrams only
- Runtime shape: one persistent reduced-product session for the repository;
  bulk forward seeding followed by shared targeted signature refinement
- Detailed event recording: disabled

## pre-commit-hooks

- Modules: 36
- Observations requested: 318
- Analysis time: 20.205 seconds
  - translation: 0.830 seconds
  - session open: 0.526 seconds
  - forward seed: 0.006 seconds
  - shared targeted refinement: 15.023 seconds
- Official TypyBench observations: 257
- Exact score: 23.74%
- Similarity-weighted score: 29.63%
- Missing: 8.56%
- Official scorer time: 31.8 seconds

Artifacts:

- `/Volumes/LaCie/Archway/typybench/runs/successor-precommit-20260813-structured-results/manifest.json`
- `/Volumes/LaCie/Archway/typybench/runs/successor-precommit-20260813-structured-results/predictions/pre-commit-hooks/pre-commit-hooks_results_w_exact.csv`
- `/Volumes/LaCie/Archway/typybench/runs/successor-precommit-20260813-structured-results/pre-commit-hooks-residual-audit.json`

## Exact residual inventory

| Class | Count |
|---|---:|
| exact | 61 |
| unconstrained `Any` | 142 |
| erased type arguments | 23 |
| missing | 22 |
| type mismatch | 8 |
| scorer-nonexact equivalent | 1 |

Against the retained `successor-full-20260813-v3` residual inventory, exact
observations increased from 55 to 61 and missing observations fell from 25 to
22. Concrete changes include:

- `util.cmd_output::return`: `Any` → exact `str`
- `util.zsplit@s`: `Any` → `Union[Any, str]`
- `pretty_format_json._autofix@new_contents`: `Any` → exact `str`
- `pretty_format_json.get_diff@target`: `Any` → exact `str`
- three hook `main` returns: missing → exact `int`

The remaining `Any` in `zsplit@s` is retained honestly: other call paths have
not yet justified a scalar product. It must be resolved by improving reusable
diagram-derived call/input semantics, not by forcing the benchmark annotation.
