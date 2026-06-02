# Archway on TypeEvalPy — Progress

**Current:** 242 / 850 exact (28.5%) · 49 / 153 files processed · 25 / 153 sound · 133 / 153 complete · run #8 (2026-06-02T16:01:12)

_Engine filter: `archway` · Last updated 2026-06-02 16:01 UTC_

## History

_Columns: **Exact** = annotations matching GT type set; **Processed** = files where the analysis emitted predictions (didn't error); **Sound** = files where every GT entry was answered correctly (full coverage); **Complete** = files where every prediction was correct (no wrong types). Note: Complete is inflated by errored files producing zero predictions, which vacuously satisfy the metric._

| # | Created | Exact | Δ | Processed | Δ | Sound | Complete | Notes |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 8 | 2026-06-02T16:01:12 | 242/850 | +0 | 49/153 | +0 | 25/153 | 133/153 | Builtin signatures landing (no attributes/generators yet) |
| 7 | 2026-06-02T05:34:33 | 242/850 | +2 | 49/153 | +0 | 25/153 | 133/153 | End-of-day snapshot |
| 6 | 2026-06-02T05:17:23 | 240/850 | +70 | 49/153 | +13 | 25/153 | 133/153 | Verify report subcommand + engine-error capture |
| 4 | 2026-06-01T22:37:16 | 170/850 | +68 | 36/153 | +7 | 22/153 | 143/153 | Re-run on current analysis layer state |
| 3 | 2026-06-01T15:37:23 | 102/850 | -1156 | 29/153 | -271 | 14/153 | 142/153 | Adapter: position-only matching (wire_name no longer carries identifier) |
| 2 | 2026-05-30T03:20:17 | 1258/77268 | +1126 | 300/5453 | +270 | 100/5453 | 5268/5453 | First autogen run — most snippets expected to short-circuit on translation |
| 1 | 2026-05-29T20:58:34 | 132/850 | — | 30/153 | — | 16/153 | 142/153 | Repopulate after DB wipe; diagnostic for any→str misses |

