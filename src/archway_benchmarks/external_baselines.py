"""External baseline orchestration.

Drives the vendored TypeEvalPy runner classes per tool, parses the
produced `*_result.json` files into harness-native predictions, scores
them via our existing scoring layer (which itself wraps
`vendor/TypeEvalPy/src/result_analyzer/`), and ingests the result as a
run in the harness store flagged as an external baseline.

Why this exists: the published TypeEvalPy leaderboard was scored on a
*different* ground-truth snapshot than the repo's current HEAD. We must
re-run the baselines against the same GT we score Archway on so any
head-to-head comparison is honest.

Result-file shape (per snippet, written by each tool's container):
  <results_root>/<tool>/<suite_path>/main_result.json

The contents follow the TypeEvalPy schema (`docs/TypeEvalPy_JSON_schema.py`)
— same shape we emit from `TypeEvalPyBenchmark.to_tool_format`.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from archway_benchmarks.benchmarks.base import Benchmark
from archway_benchmarks.benchmarks.typeevalpy import (
    TypeEvalPyBenchmark,
    _location_to_record,
    _record_to_annotation,
)
from archway_benchmarks.coverage import CoverageStatus
from archway_benchmarks.scoring.typeevalpy import _aggregate, score_snippet
from archway_benchmarks.store import (
    connect,
    create_run,
    record_scores,
    record_snippet,
    record_snippet_scores,
)
from archway_benchmarks.types import Annotation, Location

# Vendor TypeEvalPy bootstrap — runner_class uses relative paths so we must
# import it from inside vendor/TypeEvalPy/src/.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_VENDOR_SRC = _REPO_ROOT / "vendor" / "TypeEvalPy" / "src"
if str(_VENDOR_SRC) not in sys.path:
    sys.path.insert(0, str(_VENDOR_SRC))


def _ensure_docker_host_set() -> None:
    """The Python docker SDK reads DOCKER_HOST (or falls back to
    `/var/run/docker.sock`). On macOS with OrbStack the socket actually
    lives at `~/.orbstack/run/docker.sock`, so we point DOCKER_HOST there
    if it isn't already set."""
    import os as _os
    if _os.environ.get("DOCKER_HOST"):
        return
    candidates = [
        Path.home() / ".orbstack" / "run" / "docker.sock",
        Path.home() / ".docker" / "run" / "docker.sock",
        Path("/var/run/docker.sock"),
    ]
    for c in candidates:
        if c.exists():
            _os.environ["DOCKER_HOST"] = f"unix://{c}"
            return


_ensure_docker_host_set()

logger = logging.getLogger("archway_benchmarks.external_baselines")


# Map our short tool name to (runner class name, friendly label).
RUNNER_REGISTRY: dict[str, str] = {
    "headergen": "HeaderGenRunner",
    "pyright": "PyrightRunner",
    "scalpel": "ScalpelRunner",
    "jedi": "JediRunner",
    "hityper": "HityperRunner",
    "type4py": "Type4pyRunner",
    "hityperdl": "HityperDLRunner",
}


@dataclass
class ToolRunOutcome:
    tool: str
    benchmark_name: str
    run_id: int | None
    runtime_seconds: float
    image_digest: str | None
    error: str | None = None


# ----- Run vendor tool -----

def run_vendor_tool(
    tool: str,
    *,
    benchmark_corpus_dir: Path,
    results_root: Path,
    nocache: bool = False,
) -> tuple[Path, float, str | None]:
    """Build + run the vendored tool container; returns
    (per-tool results dir, wall-clock seconds, image digest).

    All paths are normalised to absolute. Runner classes expect to be invoked
    with cwd = vendor/TypeEvalPy/src so their relative dockerfile_path resolves;
    we save+restore cwd around the call.
    """
    if tool not in RUNNER_REGISTRY:
        raise ValueError(f"unknown tool {tool}; choices: {list(RUNNER_REGISTRY)}")

    import runner_class  # noqa: import inside fn so missing docker SDK surfaces here

    runner_cls = getattr(runner_class, RUNNER_REGISTRY[tool])

    results_root = results_root.resolve()
    results_root.mkdir(parents=True, exist_ok=True)

    benchmark_corpus_dir = benchmark_corpus_dir.resolve()
    if not benchmark_corpus_dir.exists():
        raise FileNotFoundError(f"benchmark corpus dir not found: {benchmark_corpus_dir}")

    saved_cwd = Path.cwd()
    image_digest: str | None = None
    start = time.monotonic()
    try:
        import os
        os.chdir(_VENDOR_SRC)
        runner_instance = runner_cls(
            host_results_path=str(results_root),
            nocache=nocache,
            custom_benchmark_dir=str(benchmark_corpus_dir),
        )
        # If an image with this tool's tag already exists and the caller
        # didn't ask for nocache, skip the runner's rebuild. This lets us
        # pre-build with platform overrides (e.g. linux/amd64 on ARM Macs)
        # and have the run reuse that image instead of clobbering the tag
        # with a freshly-built broken one.
        if not nocache:
            try:
                import docker as _docker
                client = _docker.from_env()
                existing = client.images.get(tool)
                runner_instance._build_docker_image = lambda: None  # noqa: SLF001
                logger.info("reusing pre-built image for %s: %s", tool, existing.id)
            except Exception as e:  # noqa: BLE001
                logger.debug("no pre-built image for %s; will build (%s)", tool, e)
        runner_instance.run_tool_test()
        # Pull the image digest after run so docker can resolve the build.
        try:
            import docker as _docker
            client = _docker.from_env()
            image = client.images.get(tool)
            image_digest = image.id  # e.g. "sha256:..."
        except Exception as e:  # noqa: BLE001
            logger.warning("could not retrieve image digest for %s: %s", tool, e)
    finally:
        import os as _os
        _os.chdir(saved_cwd)

    runtime = time.monotonic() - start
    tool_results_dir = results_root / tool
    return tool_results_dir, runtime, image_digest


# ----- Parse tool results into harness predictions -----

def parse_tool_results(
    tool_results_dir: Path, benchmark: Benchmark
) -> dict[Location, frozenset[str]]:
    """Walk `<tool_results_dir>/<suite_path>/main_result.json` files and
    project each record onto a harness `Location`. Skips locations that
    cannot be matched into the benchmark's snippet set (the corpus may have
    moved between the tool's view and our `Benchmark.load`)."""

    # Index snippets by absolute corpus path. Benchmark.load returns Snippets
    # with `file_path` like `<suite_path>/main.py` keyed off the benchmark's
    # corpus_root. We need to align with what the tool ran on, which uses the
    # same suite_path layout.
    snippets = benchmark.load()
    snippet_path_to_file_id = {snip.suite_path: snip.file_path for snip in snippets}

    predictions: dict[Location, frozenset[str]] = {}
    seen_files = 0
    for result_path in tool_results_dir.rglob("main_result.json"):
        suite_path = _suite_path_from_result(tool_results_dir, result_path)
        if suite_path is None:
            continue
        file_id = snippet_path_to_file_id.get(suite_path)
        if file_id is None:
            logger.debug("result file with no matching snippet: %s", suite_path)
            continue
        try:
            records = json.loads(result_path.read_text())
        except json.JSONDecodeError as e:
            logger.warning("malformed JSON in %s: %s", result_path, e)
            continue
        seen_files += 1
        for rec in records:
            try:
                annotation = _record_to_annotation(rec, file_id)
            except ValueError as e:
                logger.debug("skipped record: %s (%s)", rec, e)
                continue
            # If multiple records share a Location key, last-write-wins matches
            # the scorer's sorted-set comparison semantics.
            predictions[annotation.location] = annotation.types
    logger.info("parsed %d result files from %s", seen_files, tool_results_dir)
    return predictions


def _suite_path_from_result(tool_results_dir: Path, result_path: Path) -> str | None:
    """Extract `<category>/<scenario>` from a result file path.

    Tool containers vary in which directory they preserve when copying out:
    some keep `python_features/`, others keep `micro-benchmark/` (the
    container-side basename), others keep the autogen folder name. Strip any
    of these well-known wrappers; what's left should start with one of the
    18 python_features categories.
    """
    rel = result_path.relative_to(tool_results_dir).parent
    parts = list(rel.parts)
    while parts and parts[0] in {
        "python_features",
        "micro-benchmark",
        "autogen_typeevalpy_benchmark",
    }:
        parts = parts[1:]
    # Also strip a leading timestamped autogen dir like autogen_typeevalpy_benchmark_<ts>.
    if parts and parts[0].startswith("autogen_typeevalpy_benchmark_"):
        parts = parts[1:]
    if not parts:
        return None
    return "/".join(parts)


# ----- Ingest into harness store -----

def ingest_baseline(
    *,
    db_path: Path,
    tool: str,
    benchmark: TypeEvalPyBenchmark,
    predictions: dict[Location, frozenset[str]],
    runtime_seconds: float,
    image_digest: str | None,
    benchmark_commit: str,
    sample_size: int | None = None,
    notes: str | None = None,
    source_label: str = "regenerated",
) -> int:
    snippets = benchmark.load()
    file_id_to_suite = {snip.file_path: snip.suite_path for snip in snippets}

    gt_by_snippet: dict[str, dict[Location, frozenset[str]]] = defaultdict(dict)
    for snip in snippets:
        for ann in snip.annotations:
            gt_by_snippet[snip.suite_path][ann.location] = ann.types

    pred_by_snippet: dict[str, dict[Location, frozenset[str]]] = defaultdict(dict)
    for loc, types in predictions.items():
        suite_path = file_id_to_suite.get(loc.file)
        if suite_path is None:
            continue
        pred_by_snippet[suite_path][loc] = types

    per_snippet = [
        score_snippet(
            suite_path=snip.suite_path,
            ground_truth=gt_by_snippet[snip.suite_path],
            predictions=pred_by_snippet.get(snip.suite_path, {}),
            location_to_record=_location_to_record,
        )
        for snip in snippets
    ]
    scores = _aggregate(per_snippet)

    metadata = {
        "tool": tool,
        "image_digest": image_digest,
        "benchmark_commit": benchmark_commit,
        "benchmark_name": benchmark.name,
        "runtime_seconds": round(runtime_seconds, 2),
        "regenerated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source_label,
        "sample_size": sample_size,
    }

    with connect(db_path) as conn:
        run_id = create_run(
            conn,
            benchmark=benchmark.name,
            engine=f"external:{tool}",
            stub_accuracy=None,
            seed=None,
            notes=notes
            or f"regenerated baseline for {tool} on {benchmark.name}@{benchmark_commit[:8]}",
            metadata=metadata,
        )
        for snip in snippets:
            record_snippet(
                conn,
                run_id,
                suite_path=snip.suite_path,
                source=snip.source,
                translation_status=CoverageStatus.COVERED,
            )
        record_snippet_scores(conn, run_id, per_snippet)
        record_scores(conn, run_id, scope="all", scores=scores)
        record_scores(conn, run_id, scope="covered", scores=scores)

    logger.info(
        "ingested %s on %s as run #%d (exact %d/%d, runtime %.1fs)",
        tool,
        benchmark.name,
        run_id,
        scores.exact_total,
        scores.total_annotations,
        runtime_seconds,
    )
    return run_id


# ----- Drive one tool end-to-end -----

def run_and_ingest(
    *,
    tool: str,
    benchmark: TypeEvalPyBenchmark,
    benchmark_commit: str,
    db_path: Path,
    results_root: Path,
    nocache: bool = False,
) -> ToolRunOutcome:
    """One-call wrapper: build/run vendor tool, parse, score, persist.

    On any failure (Docker build failure, OOM, missing model server) the
    exception is captured into `ToolRunOutcome.error` rather than raised, so
    the orchestrator can checkpoint partial progress.
    """
    try:
        results_dir, runtime, image_digest = run_vendor_tool(
            tool=tool,
            benchmark_corpus_dir=Path(benchmark.corpus_root),
            results_root=results_root,
            nocache=nocache,
        )
        predictions = parse_tool_results(results_dir, benchmark)
        run_id = ingest_baseline(
            db_path=db_path,
            tool=tool,
            benchmark=benchmark,
            predictions=predictions,
            runtime_seconds=runtime,
            image_digest=image_digest,
            benchmark_commit=benchmark_commit,
        )
        return ToolRunOutcome(
            tool=tool,
            benchmark_name=benchmark.name,
            run_id=run_id,
            runtime_seconds=runtime,
            image_digest=image_digest,
        )
    except Exception as e:  # noqa: BLE001  -- we DELIBERATELY swallow per spec
        logger.exception("tool %s on %s failed", tool, benchmark.name)
        return ToolRunOutcome(
            tool=tool,
            benchmark_name=benchmark.name,
            run_id=None,
            runtime_seconds=0.0,
            image_digest=None,
            error=str(e),
        )
