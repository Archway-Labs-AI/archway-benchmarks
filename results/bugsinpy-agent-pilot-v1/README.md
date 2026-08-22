# BugsInPy agent evidence pilot v1

This is the first validity-controlled paired evaluation of an agent that may ask
Archway for targeted static-analysis evidence while localizing a bug. It is a
12-case pilot, not a population estimate for BugsInPy and not evidence that the
current query set can independently detect bugs.

## Result

The baseline and evidence-offered arms each localized 2/12 fixes at top-1 line
rank (MRR 0.1667; mean normalized inspection effort 0.8338). No evidence-arm
agent invoked Archway. Offering the optional tool therefore produced no measured
accuracy change, while costing a paired mean of 89,416 additional tokens and
15.24 additional seconds per case.

This is evidence about the current **agent/tool policy and interface**, not the
counterfactual quality of evidence that was never requested. A deterministic
post-seal diagnostic consequently asked one `possible-calls` question at each
already-sealed evidence-arm top finding. One query answered, one returned
`no_evidence`, three timed out at 60 seconds, and seven failed at a translation,
analysis, or serialization boundary. Ground-truth review classified the one
answer as correct but irrelevant to distinguishing the defect: 0 useful,
1 irrelevant, 0 misleading, and 11 unusable.

The paired and diagnostic results must not be combined. The diagnostic could not
change predictions and does not estimate an agent treatment effect.

## Validity controls

- The public cohort was committed before the run.
- Each arm saw only a complete buggy checkout and sanitized task manifest.
- Fix patches, fixed source, corpus metadata, sibling cases, prior outputs, and
  Git history-bearing objects were denied to the provider.
- Provider network access and hosted web search were independently disabled and
  attested; raw provider streams were checked for web-search events.
- Predictions were sealed before ground truth was joined for scoring.
- Model identity, model-cache hash, corpus revision, commands, repository
  revisions, raw streams, audit records, token usage, and durations are retained
  by the private runner. Hashes of the claim inputs are published in
  [`summary.json`](summary.json).

An earlier otherwise-complete run is excluded because its raw provider stream
showed hosted web searches for the BugsInPy fix. Additional setup and smoke runs
are excluded because their model or provenance was not fully pinned.

## Reproduction boundary

The public, independently inspectable pieces are:

- cohort: [`cohorts/bugsinpy-agent-pilot-v1.json`](../../cohorts/bugsinpy-agent-pilot-v1.json);
- sanitized input/prediction contracts and scorer under `src/archway_benchmarks`;
- evidence-quality decisions:
  [`adjudications/bugsinpy-agent-pilot-v1-evidence.json`](../../adjudications/bugsinpy-agent-pilot-v1-evidence.json);
- aggregate result and exact revisions: [`summary.json`](summary.json).

The internal runner is intentionally not part of the public benchmark authority.
An independent runner can reproduce the comparison by implementing the public
contracts, checking out the pinned corpus and code revisions, enforcing the same
input/network/history denials, running both prompts with the pinned model, sealing
predictions, and passing the pairs to the public scorer. Provider output cannot
be expected to be byte-for-byte deterministic; the published claim is the scored
cohort outcome and its validity controls.

## Interpretation

Do not invest further in a broad non-agentic BugsInPy detector on the strength of
this pilot. The more promising next experiment is an agentic interface that makes
query use deliberate—such as requiring a small evidence triage step or offering
queries selected from a concrete hypothesis—after the recorded usability blockers
are handed to engine owners. The next cohort should test whether queries are used
and whether useful evidence changes a diagnosis; simply exposing optional commands
again is not justified by this result.
