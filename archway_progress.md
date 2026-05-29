# Archway on TypeEvalPy — Progress

**Current:** 109 / 850 exact (12.8%) · 30 / 153 files processed · 12 / 153 sound · 138 / 153 complete · run #9 (2026-05-29T18:30:13)

_Engine filter: `archway` · Last updated 2026-05-29 18:30 UTC_

## History

_Columns: **Exact** = annotations matching GT type set; **Processed** = files where the analysis emitted predictions (didn't error); **Sound** = files where every GT entry was answered correctly (full coverage); **Complete** = files where every prediction was correct (no wrong types). Note: Complete is inflated by errored files producing zero predictions, which vacuously satisfy the metric._

| # | Created | Exact | Δ | Processed | Δ | Sound | Complete | Notes |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 9 | 2026-05-29T18:30:13 | 109/850 | +0 | 30/153 | — | 12/153 | 138/153 | Add files_processed telemetry to runs |
| 7 | 2026-05-29T18:02:36 | 109/850 | +23 | — | — | 12/153 | 138/153 | Post-genuine-restart with agent's analysis edits in place |
| 5 | 2026-05-29T17:41:45 | 86/850 | +18 | — | — | 8/153 | 133/153 | Body-env retention: params + locals + intermediates per instantiation surfaced as positioned wires |
| 4 | 2026-05-29T17:16:22 | 68/850 | +10 | — | — | 3/153 | 133/153 | Wire functions[] lookup into adapter — function: GT entries resolve to observed returns |
| 3 | 2026-05-29T16:37:42 | 58/850 | +16 | — | — | 1/153 | 124/153 | FunctionDef wires now positioned at the name column (was at the 'def' keyword) |
| 2 | 2026-05-29T15:41:51 | 42/850 | — | — | — | 1/153 | 133/153 | Dict translation + DictTag functor + ABSTRACT-function signatures (initial archway integration) |

