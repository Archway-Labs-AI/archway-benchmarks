# TypyBench holdout v1

This partition measures whether Archway's diagram analysis generalizes beyond
repositories whose residual errors inform development. Do not inspect or
classify individual false or missing predictions from these repositories.
Milestone runs may report their aggregate scores and performance evidence.

The partition was frozen on 2026-08-15 before further TypyBench semantic work.
Repositories already used for residual analysis were excluded. The remaining
names were ranked by SHA-256 of
`archway-typybench-holdout-v1:<repository-name>` and the first ten selected:

- AutoGPT
- haystack
- manim
- openai-python
- private-gpt
- rich
- streamlit
- supervision
- taipy
- urllib3

The machine-readable authority is `HOLDOUT_REPOSITORIES` in
`archway_benchmarks.typybench_partitions`. Changing the membership requires a
new version; this list must not be edited in response to its measured score.
