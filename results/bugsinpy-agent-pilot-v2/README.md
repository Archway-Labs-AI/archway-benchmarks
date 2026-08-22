# BugsInPy agent evidence pilot v2

**Non-claim-grade adoption diagnostic; not a public baseline or an Archway-effect
estimate.** This corrected run supplied a working, preflighted evidence executable
to all 12 evidence-arm agents. None invoked it. The retained internal observation is
therefore zero adoption under the optional prompt—not a comparison of reasoning with
versus without Archway evidence.

The completion audit found one remaining public-provenance defect: the root retains
the normalized run configuration and all scored artifacts, but not the exact
initiating command vector(s) used across the resumable run. Public benchmark policy
requires the command for every reported baseline. The result is published to make
that limitation and the measured diagnostics independently visible, but it is not
promoted to a claim-grade baseline.

## Observed comparison

The baseline localized 2/12 fixes at the top-ranked line and 8/12 at the top-ranked
file. The evidence-available prompt localized 3/12 lines and 9/12 files. Its mean
reciprocal rank was 0.25 versus 0.1667, and mean normalized inspection effort was
0.7505 versus 0.8338. It consumed 79,298 more tokens and 8.12 more seconds per case.

Those numerical differences cannot be attributed to Archway: query count was zero
in every pair. The arms were independent model invocations, so provider variance or
the longer tool prompt can explain the delta. Reporting the extra line hit as an
Archway improvement would invalidate the experiment.

## Validity controls

- The 12-case public cohort was committed before execution.
- All 12 pairs and 24 raw provider streams were sealed and audited.
- Each evidence arm retained a successful preflight of the exact wrapper offered to
  the agent, including wrapper and capability-response hashes and the preserved
  virtual-environment interpreter path.
- Fixes, fixed source, corpus metadata, sibling cases, previous outputs, and Git
  history were denied to providers.
- Network and hosted web search were disabled and attested; the streams contained
  zero hosted-search events.
- Predictions were sealed before ground truth was joined.
- The audit reported no issues.

These controls establish the retained internal observation. They do not cure the
missing initiating-command record required for a public baseline.

The prior [`v1`](../bugsinpy-agent-pilot-v1/) result remains invalidated because its
treatment executable was broken. It must not be combined with this run.

## Deterministic diagnostic

After sealing, a separate deterministic diagnostic issued one call-target query at
each evidence-arm top finding. It is not an agent condition and could not affect any
prediction. One query answered, one returned `no_evidence`, four timed out, and six
failed at translation, analysis, or serialization boundaries. The single answer
correctly identified `open` but could not distinguish the erroneous argument name.

This diagnostic is frozen. Repeating it with the same engine, workbench, checkout,
selector, and configuration would add no information.

## Interpretation and next gate

Command discoverability is insufficient. A patch-blind compatibility review found
that the cohort's defects chiefly require argument-flow, value-relation, ordering,
boundary, policy, or repeated-effect evidence; binding types and call targets do not
credibly distinguish the sealed hypotheses. Another cohort run is refused until one
precommitted case demonstrates a relevant bounded query and a causal before/query/
after agent trace.

The result supports pausing further non-agentic detector investment and larger
optional-tool experiments. It does not support abandoning agent-facing Archway.
Instead, it identifies the next useful engine-owned evidence surface: source-linked
call-argument flow with native provenance and explicit precision/uncertainty.

Exact aggregates, revisions, validity counts, execution-provenance disposition, and private-artifact hashes are in
[`summary.json`](summary.json). Public contracts and scoring code live under
`src/archway_benchmarks`; the private runner retains raw provider material and
internal paths that are intentionally not part of the public authority.
