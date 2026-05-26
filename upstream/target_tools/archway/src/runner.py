"""Archway runner for TypeEvalPy.

Per `docs/Tool_Integration_Guide.md`, each tool's runner is responsible for
reading the Python files under `--bechmark_path`, running its inference, and
writing one `<basename>_result.json` per `<basename>.py` containing records
in the TypeEvalPy schema.

This runner has **two backends**:

  1. **API backend** (`ARCHWAY_API_ENDPOINT` env var set)
     POSTs each file's source to the hosted Archway analysis service and
     translates the response into TypeEvalPy records via `translator`. The
     engine internals stay server-side; no Archway IR or analysis code ships
     in this container.

  2. **Stub backend** (`ARCHWAY_STUB_ACCURACY` env var set; default 0.67)
     Reads the sibling `main_gt.json` for each `main.py`, perturbs the type
     sets at the configured per-annotation accuracy, and emits TypeEvalPy
     records. The stub path is for exercising the integration end-to-end
     without a live backend — it must never be enabled in real evaluation.

If neither backend is configured **the runner fails loudly** (exit 2) rather
than emit empty results that would score as zero — the docs explicitly call
this out as a footgun for downstream consumers of the leaderboard.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from pathlib import Path
from sys import stdout

import translator
import util

# Optional dependency: only required when the API backend is active.
try:
    import requests  # type: ignore
except ImportError:  # pragma: no cover  -- absent in the stub path
    requests = None  # type: ignore


# --- logging ---
logger = logging.getLogger("runner")
logger.setLevel(logging.DEBUG)
log_file = "/tmp/archway_log.log"
fh = logging.FileHandler(log_file)
fh.setLevel(logging.DEBUG)
sh = logging.StreamHandler(stdout)
sh.setLevel(logging.DEBUG)
fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
fh.setFormatter(fmt)
sh.setFormatter(fmt)
logger.addHandler(fh)
logger.addHandler(sh)


# Pool of plausible-but-wrong type strings used by the stub backend. Matches
# the harness's StubAnalysisEngine — see the harness for canonical version.
_NOISE_POOL: tuple[str, ...] = (
    "int", "str", "float", "bool", "list", "dict", "tuple", "set",
    "bytes", "nonetype", "callable", "any", "object",
)


def _list_python_files(folder_path: str) -> list[Path]:
    return sorted(Path(folder_path).rglob("main.py"))


# --- API backend ---

def _run_via_api(file_path: Path, endpoint: str, api_key: str | None) -> list[dict]:
    if requests is None:
        raise RuntimeError(
            "API backend requested but `requests` is not installed. Rebuild the image."
        )
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    source = file_path.read_text()
    resp = requests.post(
        endpoint.rstrip("/") + "/v1/analyze",
        headers=headers,
        json={"file": str(file_path.name), "source": source},
        timeout=int(os.environ.get("ARCHWAY_API_TIMEOUT", "60")),
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Archway API returned HTTP {resp.status_code}: {resp.text[:200]}"
        )
    body = resp.json()
    annotations = body.get("annotations") or []
    return [
        translator.annotation_to_record(
            file=str(file_path.name),
            line=int(a["line"]),
            col=a.get("col"),
            kind=a["kind"],
            name=a["name"],
            function=a.get("function"),
            types=list(a.get("types", [])),
        )
        for a in annotations
    ]


# --- Stub backend ---

def _run_via_stub(file_path: Path, accuracy: float, rng: random.Random) -> list[dict]:
    gt_path = util.find_gt_path(str(file_path))
    if gt_path is None:
        raise FileNotFoundError(
            f"stub mode requires sibling {file_path.stem}_gt.json next to {file_path}"
        )
    with open(gt_path) as f:
        gt: list[dict] = json.load(f)

    out: list[dict] = []
    for rec in gt:
        types = rec.get("type", [])
        if rng.random() < accuracy:
            predicted = sorted(set(types))
        else:
            choices = [t for t in _NOISE_POOL if t not in set(types)]
            predicted = [rng.choice(choices)] if choices else ["object"]
        out_rec = dict(rec)
        out_rec["type"] = predicted
        out.append(out_rec)
    return out


def _backend_or_die() -> tuple[str, dict]:
    endpoint = os.environ.get("ARCHWAY_API_ENDPOINT", "").strip()
    if endpoint:
        return "api", {
            "endpoint": endpoint,
            "api_key": os.environ.get("ARCHWAY_API_KEY") or None,
        }
    accuracy = os.environ.get("ARCHWAY_STUB_ACCURACY")
    if accuracy is not None:
        try:
            return "stub", {"accuracy": float(accuracy), "seed": int(os.environ.get("ARCHWAY_STUB_SEED", "1"))}
        except ValueError as e:
            raise RuntimeError(
                f"ARCHWAY_STUB_ACCURACY={accuracy!r} is not a float: {e}"
            ) from e
    raise RuntimeError(
        "No backend configured. Set ARCHWAY_API_ENDPOINT for the hosted API "
        "or ARCHWAY_STUB_ACCURACY=0.67 for the local stub. Refusing to emit "
        "empty results — see target_tools/archway/README for details."
    )


def main_runner(args: argparse.Namespace) -> int:
    backend, conf = _backend_or_die()
    logger.info("backend=%s benchmark=%s", backend, args.bechmark_path)
    rng = random.Random(conf.get("seed", 1)) if backend == "stub" else None

    python_files = _list_python_files(args.bechmark_path)
    logger.info("found %d main.py files", len(python_files))
    error_count = 0
    for file in python_files:
        try:
            if backend == "api":
                inferred = _run_via_api(file, conf["endpoint"], conf.get("api_key"))
            else:
                inferred = _run_via_stub(file, conf["accuracy"], rng)  # type: ignore[arg-type]

            json_file_path = str(file).replace(".py", "_result.json")
            with open(json_file_path, "w") as jf:
                json.dump(inferred, jf, sort_keys=True, indent=4)
        except Exception as e:  # noqa: BLE001
            logger.info("non-zero exit %s for %s", e, file)
            error_count += 1
    logger.info("Runner finished with errors: %d", error_count)
    return error_count


if __name__ == "__main__":
    if not util.is_running_in_docker():
        print("Warning: Archway runner is meant to be run inside its container.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--bechmark_path", default="/tmp/micro-benchmark")
    args = parser.parse_args()
    try:
        sys.exit(0 if main_runner(args) == 0 else 1)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
