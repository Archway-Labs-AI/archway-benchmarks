# TypeEvalPy baselines · current GT · 2026-06-02T17:33:37+00:00

Headline numbers are the **regenerated-lenient** column — each tool re-run against the benchmark's current ground truth and scored with TypeEvalPy's paper-era predicate. A small Δ vs Historical reflects ground-truth drift since publication. The strict column is shown for transparency only.

## How to read each column

| Column | What it is | When to cite |
| --- | --- | --- |
| **Regenerated · lenient** (headline) | Each tool's `*_result.json` files against current GT, scored with `extras/TypeEvalPy/src/result_analyzer/large_scale_analysis.check_match` (col_offset and line checks commented out, lines 46-51). This is the predicate that generated the published board. | Head-to-head comparisons. |
| **Historical** | Published `paper_table_*.csv` from the vendored repo. Generated 14 Jan 2024 (micro) / 30 Aug 2024 (autogen) against an older GT snapshot. | As a reference. **Do not cross-compare against the regenerated columns directly** — different answer keys. |
| **Δ vs Historical** | `lenient − historical`. | Headline finding. Sign + magnitude is GT drift only (and, for autogen, generation-composition drift). |
| **Regenerated · strict** | Same outputs scored with `analysis_utils.is_same_element` (added Oct 2025, commit `2f7c6056`), which requires `col_offset` to match. Some historical tool runners do not emit `col_offset`, so strict misses can be a runner-format artifact rather than an inference result. | Transparency only; prefer the lenient column for like-for-like comparisons with published TypeEvalPy results. |


## typeevalpy

_Paper · 14 Jan 2024 · stale GT_ · extras/TypeEvalPy/docs/webview/paper_tables/paper_table_1.csv (exact match) + paper_table_3.csv (sound/complete). EXPERIMENT_RUN_ON in analysis_leaderboard.py is hardcoded to 14 Jan 2024 — these numbers were scored against the GT snapshot that existed then. GT has been updated since (April 2026 fix in commit 3719de11); use the Regenerated column for like-for-like comparison.

| Tool | FR (l) | FP (l) | LV (l) | **Total lenient** | Δ vs Historical | Historical | Strict | Sound (l) | Complete (l) | Runtime |
| --- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| **headergen** | 196 | 63 | 332 | **591** | +59 | 532 | 580 | 64/153 | 63/153 | 20s |
| **jedi** | 119 | 0 | 357 | **476** | +61 | 415 | 476 | 40/153 | 41/153 | 10s |
| **scalpel** | 140 | 33 | 10 | **183** | -14 | 197 | 180 | 0/153 | 83/153 | 16s |

### Rule buckets · A1–A5 × kind (lenient)

Cell: caught / GT-total. Buckets group annotations by ground-truth type family.


**headergen** (typeevalpy)

| Bucket | FR | FP | LV | Total | % |
| --- | ---: | ---: | ---: | ---: | ---: |
| A1 · scalars (int, str) | 144/172 | 30/55 | 140/283 | 314/510 | 62% |
| A2 · callable | 25/25 | 29/33 | 70/92 | 124/150 | 83% |
| A3 · containers (list, dict, tuple) | 8/9 | 1/3 | 55/64 | 64/76 | 84% |
| A4 · float/bool/None | 13/14 | 0/0 | 10/22 | 23/36 | 64% |
| A5 · constructor → class name | 6/10 | 3/4 | 57/64 | 66/78 | 85% |

**jedi** (typeevalpy)

| Bucket | FR | FP | LV | Total | % |
| --- | ---: | ---: | ---: | ---: | ---: |
| A1 · scalars (int, str) | 91/172 | 0/55 | 181/283 | 272/510 | 53% |
| A2 · callable | 5/25 | 0/33 | 57/92 | 62/150 | 41% |
| A3 · containers (list, dict, tuple) | 9/9 | 0/3 | 57/64 | 66/76 | 87% |
| A4 · float/bool/None | 8/14 | 0/0 | 16/22 | 24/36 | 67% |
| A5 · constructor → class name | 6/10 | 0/4 | 46/64 | 52/78 | 67% |

**scalpel** (typeevalpy)

| Bucket | FR | FP | LV | Total | % |
| --- | ---: | ---: | ---: | ---: | ---: |
| A1 · scalars (int, str) | 109/172 | 13/55 | 8/283 | 130/510 | 25% |
| A2 · callable | 8/25 | 20/33 | 0/92 | 28/150 | 19% |
| A3 · containers (list, dict, tuple) | 9/9 | 0/3 | 2/64 | 11/76 | 14% |
| A4 · float/bool/None | 9/14 | 0/0 | 0/22 | 9/36 | 25% |
| A5 · constructor → class name | 5/10 | 0/4 | 0/64 | 5/78 | 6% |

### Published Aug-2024 reference (stale GT — do not cross-compare)

| Tool | FR | FP | LV | Total |
| --- | --: | --: | --: | --: |
| HeaderGen | 185 | 56 | 291 | 532 |
| Jedi | 122 | 0 | 293 | 415 |
| Pyright | 100 | 8 | 297 | 405 |
| HiTyper-DL | 163 | 27 | 179 | 369 |
| HiTyper | 141 | 7 | 102 | 250 |
| Scalpel | 155 | 36 | 6 | 197 |
| Type4Py | 39 | 19 | 99 | 157 |

## typeevalpy_autogen

_Published 30 Aug 2024 (stale GT + different generation)_ · extras/TypeEvalPy/README.md (table generated 30 Aug 2024 against a 78,373-annotation Autogen run; our regenerated Autogen has 76,844 annotations — denominators don't even match)

| Tool | FR (l) | FP (l) | LV (l) | **Total lenient** | Δ vs Historical | Historical | Strict | Sound (l) | Complete (l) | Runtime |
| --- | --: | --: | --: | --: | --: | --: | --: | --: | --: | --: |
| **headergen** | 14086 | 350 | 38787 | **53223** | +2421 | 50802 | 49799 | 750/5453 | 1418/5453 | 88s |
| **jedi** | 12128 | 0 | 26198 | **38326** | +9763 | 28563 | 36505 | 589/5453 | 3011/5453 | 119s |
| **scalpel** | 15428 | 174 | 22 | **15624** | +52 | 15572 | 15478 | 0/5453 | 3928/5453 | 345s |

### Rule buckets · A1–A5 × kind (lenient)

Cell: caught / GT-total. Buckets group annotations by ground-truth type family.


**headergen** (typeevalpy_autogen)

| Bucket | FR | FP | LV | Total | % |
| --- | ---: | ---: | ---: | ---: | ---: |
| A1 · scalars (int, str) | 4784/5075 | 103/309 | 13940/25775 | 18827/31159 | 60% |
| A2 · callable | 242/1046 | 194/326 | 13899/16719 | 14335/18091 | 79% |
| A3 · containers (list, dict, tuple) | 4762/7228 | 17/147 | 6243/9886 | 11022/17261 | 64% |
| A4 · float/bool/None | 4239/4376 | 18/54 | 3466/4492 | 7723/8922 | 87% |
| A5 · constructor → class name | 59/273 | 18/60 | 1239/1502 | 1316/1835 | 72% |

**jedi** (typeevalpy_autogen)

| Bucket | FR | FP | LV | Total | % |
| --- | ---: | ---: | ---: | ---: | ---: |
| A1 · scalars (int, str) | 3810/5075 | 0/309 | 3638/25775 | 7448/31159 | 24% |
| A2 · callable | 85/1046 | 0/326 | 10872/16719 | 10957/18091 | 61% |
| A3 · containers (list, dict, tuple) | 5605/7228 | 0/147 | 7916/9886 | 13521/17261 | 78% |
| A4 · float/bool/None | 2623/4376 | 0/54 | 2812/4492 | 5435/8922 | 61% |
| A5 · constructor → class name | 5/273 | 0/60 | 960/1502 | 965/1835 | 53% |

**scalpel** (typeevalpy_autogen)

| Bucket | FR | FP | LV | Total | % |
| --- | ---: | ---: | ---: | ---: | ---: |
| A1 · scalars (int, str) | 4604/5075 | 27/309 | 10/25775 | 4641/31159 | 15% |
| A2 · callable | 156/1046 | 142/326 | 0/16719 | 298/18091 | 2% |
| A3 · containers (list, dict, tuple) | 7019/7228 | 0/147 | 11/9886 | 7030/17261 | 41% |
| A4 · float/bool/None | 3434/4376 | 5/54 | 1/4492 | 3440/8922 | 39% |
| A5 · constructor → class name | 215/273 | 0/60 | 0/1502 | 215/1835 | 12% |

### Published Aug-2024 reference (stale GT — do not cross-compare)

| Tool | FR | FP | LV | Total |
| --- | --: | --: | --: | --: |
| HeaderGen | 14086 | 346 | 36370 | 50802 |
| Jedi | 13160 | 0 | 15403 | 28563 |
| Scalpel | 15383 | 171 | 18 | 15572 |
| Type4Py | 3143 | 38 | 2243 | 5424 |

## Honest summary

**typeevalpy (lenient, current GT):** headergen (591) > jedi (476) > scalpel (183).

**typeevalpy_autogen (lenient, current GT):** headergen (53223) > jedi (38326) > scalpel (15624).

Solid: HeaderGen, Jedi, Scalpel — close-to-published numbers under the lenient (paper-era) scorer, with Δ explainable by the April-2026 inheritance/MRO ground-truth update (commit `3719de11`) and the 845→850 micro composition change.

Shaky / not run: Pyright (LSP stuck >40 min on micro; needs a longer budget or a non-LSP runner); HiTyper (vendor Dockerfile expects a `requirements.txt` that's missing from `extras/TypeEvalPy/src/target_tools/hityper/` — upstream bug); Type4Py / HiTyper-DL (require a model server we are not running). For now, **only the three solid tools should be cited** as regenerated-on-current-GT baselines.

Under the **strict** scorer (`is_same_element`, commit `2f7c6056` Oct 2025, requires col_offset match), some historical runners lose matches because they do not emit col_offset. This is a runner-format/scorer-compatibility issue, not necessarily an inference failure.

## Reference fixtures

- **Live rule-bucket scoreboard** is on every run's dashboard page (`/runs/<id>`), section *Rule buckets · A1–A5 × kind* — read this to see which type families a run covers.
- **Clean A1+A2 reference fixture** (`tests/test_a1_a2_reference.py`): pinned at **660 / 850 micro** (77.6%) and **49,176 / 77,223 autogen** (63.7%). This fixture is a harness sanity check for scalar/callable coverage, not a public benchmark result.
