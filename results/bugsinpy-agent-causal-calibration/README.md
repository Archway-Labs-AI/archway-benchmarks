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

## Matched-control Keras calibration

`keras-37-matched-v1.json` is the first validity-controlled forked comparison.
One sealed repository-only proposal selected one query; two independent reviews
then received either the actual Archway response or a truthful runner-withheld
`not_collected` control response. Review order was deterministically evidence
then control. This removes the earlier confound between “received Archway” and
“received a second model pass.” Keras 37 is calibration-only and is excluded
from the precommitted 12-case effect-estimation cohort.

Both reviews found the correct patch-derived line region. The proposal had the
correct file and causal diagnosis but its narrow lines missed the scorer's
changed-line set. Therefore both reviews improved over the proposal, while the
primary evidence-minus-control delta was exactly zero for line hit, reciprocal
rank, and EXAM. The agent-selected query was:

```text
possible-calls(keras.layers.wrappers, row=331, col=16)
```

Archway returned structured `unsupported` uncertainty—
`ProductionCapabilityRefusal: load has no preceding store for has_arg`—rather
than crashing or presenting absence as semantic evidence. The evidence review
remained correct but did not improve over control, so the response is
adjudicated `unusable`, not `misleading`.

Measured matched costs:

- shared proposal: 79,281 tokens and 32.868 seconds;
- control review: 162,344 tokens and 54.127 seconds;
- evidence review: 117,496 tokens and 61.002 seconds;
- evidence minus control review: -44,848 tokens and +6.876 seconds;
- query: one call and 1.556 seconds;
- evidence disposition: 0 useful, 0 irrelevant, 0 misleading, 1 unusable.

Pinned execution identities:

- BugsInPy corpus: `316b95e2353ecda832bad9b42f86fa7c2fcec8ac`;
- detector input: `829e7e2cb11bbcfcf6821f427ba9b6dde431020b466244acf06a256021fe95f1`;
- engine: `beb4f1f1ab497fa5c409097d804c56eff8df7b9f`;
- Workbench: `bf89f51aa47eb202684f30f65735d9762b6ca007`;
- harness cage: `8a7f32592fa4f514ac1367a59f879ec9ef64c893`;
- private runner: `8f22e2eaa4e793abf455219551801a3015f1f214`;
- public benchmark contract: `b13b89eed6a5d86e9c7b69e963fd2149f9a82c09`.

Artifact hashes:

- `keras-37-matched-v1.json`: `ebfcd255777da570a16b6cfc3263f5f2d4c708d64d9694667c2ee75c1c0ddf58`;
- `keras-37-matched-score.json`: `70d4bcddf3535bfa8e65e5461b33a8d5e59985350ceea62cfc0ffe6d75767854`.

Reproduce scoring from the repository root:

```sh
PYTHONPATH=src python3 -m archway_benchmarks.bugsinpy_agent_causal_scoring \
  --corpus-root extras/BugsInPy \
  --comparison results/bugsinpy-agent-causal-calibration/keras-37-matched-v1.json \
  --output /tmp/bugsinpy-keras-37-matched-score.json
```

This result does not authorize the 12-case run. The bounded `has_arg`
projection gap has been handed to the analysis worker, and another useful
one-case gate is required before scaling.
