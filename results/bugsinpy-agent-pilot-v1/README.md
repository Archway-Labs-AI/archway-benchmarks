# BugsInPy agent evidence pilot v1

**Invalidated — excluded from effectiveness claims.** The evidence executable
recorded in this run resolved its virtual-environment interpreter symlink to bare
system Python and omitted the engine root from `PYTHONPATH`. Had an agent invoked
it, it would have failed before analysis. The aggregate numbers remain below as
diagnostic evidence about the prompt conditions and to make the invalidation
independently visible; they are not a valid comparison of an agent with versus
without a working Archway tool.

## Result

The baseline and nominal evidence-offered arms each localized 2/12 fixes at top-1 line
rank (MRR 0.1667; mean normalized inspection effort 0.8338). No evidence-arm
agent invoked Archway. Offering the optional tool therefore produced no measured
accuracy change, while costing a paired mean of 89,416 additional tokens and
15.24 additional seconds per case.

Because the treatment executable was not usable, this does not establish an
agent/tool effect even though no agent attempted a query. A deterministic
post-seal diagnostic consequently asked one `possible-calls` question at each
already-sealed evidence-arm top finding. One query answered, one returned
`no_evidence`, three timed out at 60 seconds, and seven failed at a translation,
analysis, or serialization boundary. Ground-truth review classified the one
answer as correct but irrelevant to distinguishing the defect: 0 useful,
1 irrelevant, 0 misleading, and 11 unusable.

The invalid paired and diagnostic results must not be combined. The diagnostic could not
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
  by the private runner. Hashes of the excluded run inputs are published in
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

No investment decision may rest on this invalid paired comparison. Its post-seal
diagnostic still supplies useful engineering reproductions, but a corrected fresh
root is required before evaluating agentic versus non-agentic direction. The fixed
runner preserves the virtual-environment entry path, adds the engine root to
`PYTHONPATH`, and requires the exact treatment executable to advertise both query
capabilities before launching an agent.
