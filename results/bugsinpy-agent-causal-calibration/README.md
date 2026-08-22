# BugsInPy causal evidence calibration

Status: one validly sealed calibration interaction; not an effectiveness
baseline and not representative of BugsInPy.

The normalized `fastapi:1` record was exported from the private sealed
interaction only after oracle adjudication. It contains two independent
`gpt-5.6-sol` invocations separated by one runner-executed `call-arguments`
query. Both model stages were denied the fix, corpus, Git history, benchmark
runner, sibling checkouts, network tools, and the oracle eligibility record.

The proposal already achieved a top-1 exact patch-derived line hit. The review
retained that hit and narrowed an eight-line span to two exact lines, improving
EXAM from `0.0002774` to `0.0000347`, but it did not improve line-hit accuracy
or reciprocal rank. The Archway answer was accurate about omitted `by_alias`
forwarding but unrelated to the benchmark's `exclude_defaults` /
`exclude_none` defect, so its disposition is `irrelevant`.

Measured cost:

- proposal: 105,311 tokens;
- review increment: 60,074 tokens;
- total: 165,385 tokens and 91.272 seconds;
- query: one call, 15.849 seconds;
- evidence: 0 useful, 1 irrelevant, 0 misleading, 0 unusable.

Pinned execution identities:

- BugsInPy corpus: `316b95e2353ecda832bad9b42f86fa7c2fcec8ac`;
- engine: `5b235303a1598c666e2788389b3bcaac5554ab8f`;
- workbench: `94e3d21fdd8f27f4e97c87a476b85f07f09a11e6`;
- harness cage: `8a7f32592fa4f514ac1367a59f879ec9ef64c893`;
- private two-stage runner at execution: `66d03a60778b24f1aecc3f2251ba10bc57bdecac`.

Artifact hashes:

- `fastapi-1.json`: `dfaaa3eee6979545a981902e367897f1b130ba385e128d5d40eba9bb8daa21de`;
- `score.json`: `bee7faab807e4da55dc1ff9b9fd24f6deaeda2e628167e7115f24f7c94e678fe`.

Reproduce scoring from the repository root:

```sh
PYTHONPATH=src python3 -m archway_benchmarks.bugsinpy_agent_causal_scoring \
  --corpus-root extras/BugsInPy \
  --interaction results/bugsinpy-agent-causal-calibration/fastapi-1.json \
  --output /tmp/bugsinpy-causal-score.json
```

The three-case scale gate remains refused. Further causal runs require a direct,
oracle-isolated, technically answered calibration query.
