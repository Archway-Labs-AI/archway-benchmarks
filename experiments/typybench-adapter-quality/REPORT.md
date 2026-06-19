# TypyBench Adapter Clean Branch

Goal: clean up `feat/typybench-machinery` into a mergeable TypyBench adapter branch.

## Summary

The original `feat/typybench-machinery` branch mixed the intended TypyBench adapter work with stale-base drift and large generated attribution artifacts. This clean branch was cut from current `main` and carries only the mergeable adapter surface:

- `src/archway_benchmarks/typybench_archway_emit.py`
- `src/archway_benchmarks/typybench_harness.py`
- `tests/test_typybench_archway_emit.py`
- `tests/test_typybench_harness.py`

The bulky generated artifacts from the attribution workstream are intentionally not included. They remain available on the old branch for audit, but they are not needed in the merge diff.

## Included Fixes

- Render `NoneType` and `builtins.NoneType` as valid annotation literal `None`.
- Render raw `ellipsis` pytypes as an honest `Any` fallback instead of invalid lowercase `ellipsis`.
- Preserve container element/key/value types when the raw Archway type carries them.
- Keep `Union[...]` spelling parseable and import `typing` names as needed.
- Add opt-in JSONL trace support through `ARCHWAY_TYPYBENCH_TRACE_JSONL`; tracing is disabled by default and does not affect scoring.
- Add a thin TypyBench harness for source-tree prediction layout, single-repo staging, command construction, and result CSV parsing.

## Excluded From This Clean Branch

- copied `paper-qa` prediction source trees;
- `paper-qa_result_dict.pkl`;
- large trace dumps and generated CSVs;
- the 10k-line generated `git_diff.patch`;
- stale-base changes to docs, pyproject metadata, BugsInPy scripts, TypeEvalPy submodule state, and unrelated benchmark files.

## Verification

Run from `/Users/remote/Technical_Projects/archway-benchmarks-typybench-clean`:

```sh
test -x .venv/bin/python && .venv/bin/python -m pytest \
  tests/test_typybench_archway_emit.py tests/test_typybench_harness.py \
  || python3 -m pytest tests/test_typybench_archway_emit.py tests/test_typybench_harness.py
git diff --check --cached
```

Result:

```text
17 passed
git diff --check --cached: clean
```

The pytest run emitted a sandbox cache warning because this managed environment could not create `.pytest_cache`; test execution itself passed.
