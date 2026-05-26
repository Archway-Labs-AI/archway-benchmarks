# Archway · TypeEvalPy tool integration

Drops into `src/target_tools/archway/` of a TypeEvalPy fork. Follows
`docs/Tool_Integration_Guide.md`.

## Backends

Configured by environment variables — never hard-coded.

| Backend | Trigger | Behaviour |
|---|---|---|
| **Hosted API** | `ARCHWAY_API_ENDPOINT=https://...` (and optional `ARCHWAY_API_KEY`) | POSTs each snippet to the Archway analysis service, translates the response into TypeEvalPy records. |
| **Stub** | `ARCHWAY_STUB_ACCURACY=0.67` | Reads each snippet's sibling `main_gt.json`, perturbs the type sets at the configured per-annotation accuracy, and emits records. **For pipeline validation only.** |

If neither is set the runner exits with code 2 rather than silently emit empty results — empty results would score as `0 / N` and corrupt the leaderboard. See `runner.py:_backend_or_die`.

## Schema mapping

`src/typeevalpy_mapping.py` is the canonical Location ↔ TypeEvalPy record mapping. It is a byte-identical mirror of the harness's `archway-benchmarks/src/archway_benchmarks/typeevalpy_mapping.py`; the harness's CI enforces parity. Edits go in the harness; run `scripts/sync_upstream_mapping.py` to refresh this copy.

## Wiring into the runner

Apply `upstream/runner_class_patch.py.add` to `src/runner_class.py` (or hand-copy the `ArchwayRunner` class shown there). Add `"archway"` to `main_runner.py`'s default `--runners` list if you want it on the default board.

## Running

```bash
# Stub mode (no backend needed; emits at the configured accuracy)
docker build -t archway .
ARCHWAY_STUB_ACCURACY=0.67 python src/main_runner.py --runners archway

# API mode
ARCHWAY_API_ENDPOINT=https://api.example.com \
ARCHWAY_API_KEY=$KEY \
python src/main_runner.py --runners archway
```

The runner emits one `main_result.json` per `main.py`. Score with the standard `result_analyzer` — no Archway-specific code touches the scorer.

## What does NOT ship in the container

- Archway's translation engine.
- Archway's analysis engine.
- Archway's categorical IR.

The container is a thin client. All engine logic stays behind the hosted API.
