# Archway on TypeEvalPy — Progress

**Current:** 52266 / 77268 exact (67.6%) · 5439 / 5453 files processed · 1014 / 5453 sound · 1694 / 5453 complete · run #45 (2026-06-05T17:05:49)

_Engine filter: `archway` · Last updated 2026-06-05 17:05 UTC_

## History

_Columns: **Exact** = annotations matching GT type set; **Processed** = files where the analysis emitted predictions (didn't error); **Sound** = files where every GT entry was answered correctly (full coverage); **Complete** = files where every prediction was correct (no wrong types). Note: Complete is inflated by errored files producing zero predictions, which vacuously satisfy the metric._

| # | Created | Exact | Δ | Processed | Δ | Sound | Complete | Notes |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 45 | 2026-06-05T17:05:49 | 52266/77268 | +51667 | 5439/5453 | +5287 | 1014/5453 | 1694/5453 | loop worktree |
| 44 | 2026-06-05T17:03:49 | 599/850 | -51589 | 152/153 | -5287 | 62/153 | 107/153 | loop worktree |
| 43 | 2026-06-05T13:48:32 | 52188/77268 | +51590 | 5439/5453 | +5287 | 1014/5453 | 1652/5453 | loop worktree |
| 42 | 2026-06-05T13:46:36 | 598/850 | -50979 | 152/153 | -5203 | 62/153 | 106/153 | loop worktree |
| 41 | 2026-06-05T07:00:24 | 51577/77268 | +50992 | 5355/5453 | +5205 | 918/5453 | 1609/5453 | loop worktree |
| 40 | 2026-06-05T06:59:14 | 585/850 | +15 | 150/153 | +0 | 58/153 | 102/153 | loop worktree |
| 39 | 2026-06-05T06:13:17 | 570/850 | +11 | 150/153 | +0 | 57/153 | 101/153 | loop worktree |
| 38 | 2026-06-05T01:05:39 | 559/850 | -50815 | 150/153 | -5205 | 57/153 | 98/153 | loop worktree |
| 37 | 2026-06-04T21:47:38 | 51374/77268 | +50815 | 5355/5453 | +5205 | 916/5453 | 1626/5453 | loop worktree |
| 36 | 2026-06-04T21:45:53 | 559/850 | -50815 | 150/153 | -5205 | 57/153 | 98/153 | loop worktree |
| 35 | 2026-06-04T14:33:22 | 51374/77268 | +50815 | 5355/5453 | +5205 | 916/5453 | 1626/5453 | loop worktree |
| 34 | 2026-06-04T14:30:38 | 559/850 | +50 | 150/153 | +13 | 57/153 | 98/153 | _(no notes)_ |
| 33 | 2026-06-04T04:57:55 | 509/850 | -29863 | 137/153 | -4265 | 55/153 | 107/153 | _(no notes)_ |
| 24 | 2026-06-03T06:31:12 | 30372/77268 | +29863 | 4402/5453 | +4265 | 913/5453 | 2576/5453 | Autogen run with multi-module endpoint |
| 23 | 2026-06-03T06:29:03 | 509/850 | +509 | 137/153 | +137 | 55/153 | 107/153 | Engine resolves snippet path against corpus root for GET endpoint |
| 22 | 2026-06-03T06:26:52 | 0/850 | -449 | 0/153 | -103 | 0/153 | 153/153 | Multi-module GET endpoint live |
| 21 | 2026-06-03T05:38:18 | 449/850 | +51 | 103/153 | +0 | 39/153 | 124/153 | Adapter handles instance + class element kinds |
| 20 | 2026-06-03T05:00:54 | 398/850 | +55 | 103/153 | +34 | 35/153 | 114/153 | Quick-support batch |
| 19 | 2026-06-03T00:38:35 | 343/850 | +48 | 69/153 | +10 | 33/153 | 123/153 | Adapter consumes per-name binding-event arrays (ADR-046 update) |
| 18 | 2026-06-02T23:07:43 | 295/850 | +28 | 59/153 | +2 | 25/153 | 131/153 | Multiple analysis updates including position fixes |
| 17 | 2026-06-02T21:33:46 | 267/850 | +10 | 57/153 | +3 | 24/153 | 128/153 | Container attribute support landing |
| 16 | 2026-06-02T19:02:55 | 257/850 | +8 | 54/153 | +1 | 22/153 | 129/153 | After analysis agent's follow-up changes |
| 15 | 2026-06-02T17:48:15 | 249/850 | +7 | 53/153 | +4 | 22/153 | 130/153 | Adapter rewrite for ADR-046 FinalizedAnalysis shape |
| 8 | 2026-06-02T16:01:12 | 242/850 | +0 | 49/153 | +0 | 25/153 | 133/153 | Builtin signatures landing (no attributes/generators yet) |
| 7 | 2026-06-02T05:34:33 | 242/850 | +2 | 49/153 | +0 | 25/153 | 133/153 | End-of-day snapshot |
| 6 | 2026-06-02T05:17:23 | 240/850 | +70 | 49/153 | +13 | 25/153 | 133/153 | Verify report subcommand + engine-error capture |
| 4 | 2026-06-01T22:37:16 | 170/850 | +68 | 36/153 | +7 | 22/153 | 143/153 | Re-run on current analysis layer state |
| 3 | 2026-06-01T15:37:23 | 102/850 | -1156 | 29/153 | -271 | 14/153 | 142/153 | Adapter: position-only matching (wire_name no longer carries identifier) |
| 2 | 2026-05-30T03:20:17 | 1258/77268 | +1126 | 300/5453 | +270 | 100/5453 | 5268/5453 | First autogen run — most snippets expected to short-circuit on translation |
| 1 | 2026-05-29T20:58:34 | 132/850 | — | 30/153 | — | 16/153 | 142/153 | Repopulate after DB wipe; diagnostic for any→str misses |

