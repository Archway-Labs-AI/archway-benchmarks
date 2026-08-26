"""Emit TypyBench predictions from one persistent successor analysis session.

TypyBench scores annotated source trees.  Archway analysis remains diagram-only;
the AST is used here solely as a post-analysis output adapter that inserts facts
already produced by the successor runtime into a copy of the source tree.
"""
from __future__ import annotations

import ast
import json
import os
import re
import signal
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from archway_benchmarks.typybench_harness import require_python_source_files


_NONE_TYPE_NAMES = {"builtins.NoneType", "NoneType"}
_TRACE_ENV_VAR = "ARCHWAY_TYPYBENCH_TRACE_JSONL"


def _probe_progress(stderr: str) -> dict[str, Any]:
    """Parse low-overhead phase/cohort evidence from an incomplete probe."""

    phases: dict[str, float | int] = {}
    body_profiles: list[dict[str, Any]] = []
    body_plan: list[list[str]] = []
    translation_files: list[dict[str, Any]] = []
    active_translation_file: str | None = None
    active_body: dict[str, Any] | None = None
    for line in stderr.splitlines():
        if line.startswith("ARCHWAY_PHASE "):
            parts = line.split(" ", 2)
            if len(parts) != 3:
                continue
            name, raw_value = parts[1:]
            try:
                phases[name] = (
                    int(raw_value)
                    if name in {"signature_demands", "body_roots"}
                    else float(raw_value)
                )
            except ValueError:
                continue
        elif line.startswith("ARCHWAY_BODY_PLAN "):
            try:
                candidate = json.loads(
                    line.removeprefix("ARCHWAY_BODY_PLAN ")
                )
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, list) and all(
                isinstance(batch, list)
                and all(isinstance(item, str) for item in batch)
                for batch in candidate
            ):
                body_plan = candidate
        elif line.startswith("ARCHWAY_BODY_START "):
            parts = line.split(" ", 3)
            if len(parts) != 4:
                continue
            _prefix, position, label, root_id = parts
            try:
                index, total = (int(item) for item in position.split("/", 1))
            except ValueError:
                continue
            active_body = {
                "index": index,
                "total": total,
                "label": label,
                "root_id": root_id,
            }
        elif line.startswith("ARCHWAY_BODY "):
            parts = line.split(" ", 5)
            if len(parts) != 6:
                continue
            _prefix, position, raw_seconds, raw_exec, raw_topology, label = parts
            try:
                index, total = (int(item) for item in position.split("/", 1))
                body_profiles.append({
                    "index": index,
                    "total": total,
                    "seconds": float(raw_seconds),
                    "executions": int(raw_exec.removeprefix("exec=")),
                    "topology_changes": int(
                        raw_topology.removeprefix("topology=")
                    ),
                    "label": label,
                })
                if active_body is not None and active_body["index"] == index:
                    active_body = None
            except ValueError:
                continue
        elif line.startswith("ARCHWAY_BODY_DETAIL "):
            try:
                detail = json.loads(
                    line.removeprefix("ARCHWAY_BODY_DETAIL ")
                )
            except json.JSONDecodeError:
                continue
            if not isinstance(detail, dict):
                continue
            index = detail.get("index")
            profile = next(
                (
                    item for item in reversed(body_profiles)
                    if item["index"] == index
                ),
                None,
            )
            if profile is not None:
                profile["performance_detail"] = {
                    key: detail[key]
                    for key in (
                        "top_execution_families",
                        "top_family_seconds",
                        "top_production_operations",
                        "top_production_seconds",
                        "top_production_phases",
                        "top_production_phase_seconds",
                        "top_transfer_operations",
                        "top_transfer_seconds",
                        "topology_change_counts",
                        "component_edge_updates",
                        "gc",
                    )
                    if key in detail
                }
        elif line.startswith("ARCHWAY_TRANSLATION_START "):
            active_translation_file = line.removeprefix(
                "ARCHWAY_TRANSLATION_START "
            )
        elif line.startswith("ARCHWAY_TRANSLATION_DONE "):
            parts = line.split(" ", 3)
            if len(parts) != 4:
                continue
            try:
                translation_files.append({
                    "seconds": float(parts[1]),
                    "status": parts[2],
                    "file": parts[3],
                })
                active_translation_file = None
            except ValueError:
                continue
    return {
        "phase_progress": phases,
        "body_plan": body_plan,
        "body_profiles": body_profiles,
        "active_body": active_body,
        "active_translation_file": active_translation_file,
        "slow_translation_files": sorted(
            translation_files,
            key=lambda item: (-item["seconds"], item["file"]),
        )[:20],
    }


@dataclass(frozen=True)
class FileProfile:
    repo_name: str
    file: str
    status: str
    seconds_total: float
    seconds_engine_probe: float
    seconds_render: float = 0.0
    seconds_annotate: float = 0.0
    functions_seen: int = 0
    functions_annotated: int = 0
    params_annotated: int = 0
    returns_annotated: int = 0
    variables_annotated: int = 0
    error: str | None = None
    trace_tail: str | None = None
    analysis_summary: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "repo": self.repo_name,
            "file": self.file,
            "status": self.status,
            "seconds_total": self.seconds_total,
            "seconds_engine_probe": self.seconds_engine_probe,
            "seconds_render": self.seconds_render,
            "seconds_annotate": self.seconds_annotate,
            "functions_seen": self.functions_seen,
            "functions_annotated": self.functions_annotated,
            "params_annotated": self.params_annotated,
            "returns_annotated": self.returns_annotated,
            "variables_annotated": self.variables_annotated,
            "error": self.error,
            "trace_tail": self.trace_tail,
            "analysis_summary": self.analysis_summary,
        }


@dataclass(frozen=True)
class EmitStats:
    repo_name: str
    files_total: int
    files_analyzed: int
    files_failed: int
    functions_seen: int
    functions_annotated: int
    params_annotated: int
    returns_annotated: int
    variables_annotated: int = 0
    seconds_engine_probe: float = 0.0
    failures: tuple[dict[str, str], ...] = field(default_factory=tuple)
    file_profiles: tuple[FileProfile, ...] = field(default_factory=tuple)
    engine_sha: str | None = None
    analysis_summary: dict[str, Any] | None = None
    probe_error: str | None = None
    probe_trace_tail: str | None = None


def emit_archway_predictions(
    *,
    repo_name: str,
    untyped_root: Path,
    predictions_root: Path,
    engine_worktree: Path,
    engine_sha: str | None = None,
    overwrite: bool = True,
    runner: tuple[str, ...] = ("hatch", "run", "python"),
    timeout: int = 900,
    per_file_timeout: int = 60,
    trace_jsonl: Path | None = None,
    profile_jsonl: Path | None = None,
    progress_log: Path | None = None,
    analysis_observation_mode: str = "summary",
    checkpoint_roots: bool = True,
    body_timeout: int | None = None,
    body_labels: tuple[str, ...] | None = None,
    checkpoint_batch_start: int | None = None,
    checkpoint_batch_count: int | None = None,
    checkpoint_replay_prefix: bool = True,
    run_forward_seed: bool = True,
    progress_timeout: int | None = None,
    sample_session_open: bool = False,
    sample_forward: bool = False,
    sample_rate_hz: float | None = None,
    session_open_timeout: int | None = None,
    forward_timeout: int | None = None,
    emit_variable_annotations: bool = False,
    emit_class_field_annotations: bool = False,
) -> EmitStats:
    """Analyze one TypyBench repo and write ``predictions/<repo_name>``.

    Files that the engine cannot analyze are still copied, unannotated. That is
    the honest TypyBench contract: unsupported locations remain missing instead
    of being fabricated.
    """

    untyped_root = Path(untyped_root)
    files = require_python_source_files(
        untyped_root,
        label=f"TypyBench repo {repo_name!r} repo_without_types",
        suffixes=(".py",),
    )
    dest_root = Path(predictions_root) / repo_name
    if overwrite and dest_root.exists():
        shutil.rmtree(dest_root)
    if not dest_root.exists():
        dest_root.mkdir(parents=True)

    for src in files:
        dest = dest_root / src.relative_to(untyped_root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    trace_path = trace_jsonl or _trace_path_from_env()
    trace = _TraceWriter(trace_path, repo_name) if trace_path else None
    profile_writer = _ProfileWriter(profile_jsonl) if profile_jsonl else None

    files_analyzed = 0
    functions_seen = 0
    functions_annotated = 0
    params_annotated = 0
    returns_annotated = 0
    variables_annotated = 0
    failures: list[dict[str, str]] = []
    file_profiles: list[FileProfile] = []

    try:
        started = time.monotonic()
        probe_started = time.monotonic()
        repo_record = _run_successor_repo_probe(
            engine_worktree=Path(engine_worktree),
            source_root=untyped_root,
            runner=runner,
            timeout=timeout,
            progress_log=progress_log,
            checkpoint_roots=checkpoint_roots,
            body_timeout=body_timeout,
            body_labels=body_labels,
            checkpoint_batch_start=checkpoint_batch_start,
            checkpoint_batch_count=checkpoint_batch_count,
            checkpoint_replay_prefix=checkpoint_replay_prefix,
            run_forward_seed=run_forward_seed,
            progress_timeout=progress_timeout,
            sample_session_open=sample_session_open,
            sample_forward=sample_forward,
            sample_rate_hz=sample_rate_hz,
            session_open_timeout=session_open_timeout,
            forward_timeout=forward_timeout,
            diagnostic_details=(
                analysis_observation_mode == "diagnostic"
            ),
            record_timings=(analysis_observation_mode == "diagnostic"),
            observation_kinds=frozenset((
                "parameter",
                "return",
                *(("variable",) if emit_variable_annotations else ()),
            )),
        )
        seconds_repo_probe = time.monotonic() - probe_started
        for src in files:
            file_started = time.monotonic()
            rel = src.relative_to(untyped_root)
            rel_s = str(rel)
            dest = dest_root / rel
            record = repo_record
            # The engine probe is one repository-wide persistent session.
            # Per-file rows must not each claim its complete wall time.
            seconds_probe = 0.0
            # Preserve the probe's compact phase/cohort evidence when the
            # repository-wide subprocess itself consumed the timeout.  The
            # elapsed-budget check below used to replace this richer failure
            # with one generic error per file.
            if not record.get("ok"):
                err = str(record.get("error", "no engine result"))[:300]
                failures.append({"file": rel_s, "error": err})
                profile = FileProfile(
                    repo_name=repo_name,
                    file=rel_s,
                    status="engine_failed",
                    seconds_total=round(time.monotonic() - file_started, 6),
                    seconds_engine_probe=round(seconds_probe, 6),
                    error=err,
                    trace_tail=record.get("trace_tail"),
                    analysis_summary=record.get("analysis_summary"),
                )
                file_profiles.append(profile)
                if profile_writer:
                    profile_writer.write(profile)
                continue

            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                error = f"TimeoutExpired: repo analysis exceeded {timeout}s"
                failures.append({"file": rel_s, "error": error})
                profile = FileProfile(
                    repo_name=repo_name,
                    file=rel_s,
                    status="repo_timeout",
                    seconds_total=round(time.monotonic() - file_started, 6),
                    seconds_engine_probe=0.0,
                    error=error,
                )
                file_profiles.append(profile)
                if profile_writer:
                    profile_writer.write(profile)
                continue

            translation_failures = (
                record.get("analysis_summary", {})
                .get("translation_failures", {})
            )
            if rel_s in translation_failures:
                err = str(translation_failures[rel_s])[:300]
                failures.append({"file": rel_s, "error": err})
                profile = FileProfile(
                    repo_name=repo_name,
                    file=rel_s,
                    status="translation_failed",
                    seconds_total=round(time.monotonic() - file_started, 6),
                    seconds_engine_probe=round(seconds_probe, 6),
                    error=err,
                    analysis_summary=record.get("analysis_summary"),
                )
                file_profiles.append(profile)
                if profile_writer:
                    profile_writer.write(profile)
                continue

            files_analyzed += 1
            file_trace = trace.for_file(rel_s) if trace else None
            render_started = time.monotonic()
            function_types = _successor_function_types(
                record.get("files", {}).get(rel_s, []), trace=file_trace
            )
            variable_types = (
                _successor_variable_types(
                    record.get("files", {}).get(rel_s, []), trace=file_trace
                )
                if emit_variable_annotations else
                _successor_variable_types(
                    record.get("files", {}).get(rel_s, []),
                    trace=file_trace,
                    class_fields_only=True,
                )
                if emit_class_field_annotations else {}
            )
            seconds_render = time.monotonic() - render_started
            functions_seen += len(function_types)
            raw = src.read_text(encoding="utf-8")
            annotate_started = time.monotonic()
            try:
                annotated, file_stats = _annotate_source(
                    raw,
                    function_types,
                    variable_types=variable_types,
                    trace=file_trace,
                )
            except SyntaxError as exc:
                error = f"emit SyntaxError: {exc}"[:300]
                failures.append({"file": rel_s, "error": error})
                profile = FileProfile(
                    repo_name=repo_name,
                    file=rel_s,
                    status="annotate_failed",
                    seconds_total=round(time.monotonic() - file_started, 6),
                    seconds_engine_probe=round(seconds_probe, 6),
                    seconds_render=round(seconds_render, 6),
                    seconds_annotate=round(time.monotonic() - annotate_started, 6),
                    functions_seen=len(function_types),
                    error=error,
                    analysis_summary=record.get("analysis_summary"),
                )
                file_profiles.append(profile)
                if profile_writer:
                    profile_writer.write(profile)
                continue
            seconds_annotate = time.monotonic() - annotate_started
            functions_annotated += file_stats["functions"]
            params_annotated += file_stats["params"]
            returns_annotated += file_stats["returns"]
            variables_annotated += file_stats["variables"]
            dest.write_text(annotated, encoding="utf-8")
            profile = FileProfile(
                repo_name=repo_name,
                file=rel_s,
                status="ok",
                seconds_total=round(time.monotonic() - file_started, 6),
                seconds_engine_probe=round(seconds_probe, 6),
                seconds_render=round(seconds_render, 6),
                seconds_annotate=round(seconds_annotate, 6),
                functions_seen=len(function_types),
                functions_annotated=file_stats["functions"],
                params_annotated=file_stats["params"],
                returns_annotated=file_stats["returns"],
                variables_annotated=file_stats["variables"],
                analysis_summary=record.get("analysis_summary"),
            )
            file_profiles.append(profile)
            if profile_writer:
                profile_writer.write(profile)
    finally:
        if profile_writer:
            profile_writer.close()

    if trace:
        trace.close()

    return EmitStats(
        repo_name=repo_name,
        files_total=len(files),
        files_analyzed=files_analyzed,
        files_failed=len(files) - files_analyzed,
        functions_seen=functions_seen,
        functions_annotated=functions_annotated,
        params_annotated=params_annotated,
        returns_annotated=returns_annotated,
        variables_annotated=variables_annotated,
        seconds_engine_probe=round(seconds_repo_probe, 6),
        failures=tuple(failures),
        file_profiles=tuple(file_profiles),
        engine_sha=engine_sha,
        analysis_summary=repo_record.get("analysis_summary"),
        probe_error=(
            str(repo_record.get("error", "no engine result"))[:300]
            if not repo_record.get("ok") else None
        ),
        probe_trace_tail=repo_record.get("trace_tail"),
    )


def _successor_function_types(
    observations: list[dict[str, Any]], trace: _TraceBuffer | None = None
) -> dict[tuple[int, str], dict[str, Any]]:
    """Render compact successor observations into the annotation adapter shape."""

    candidates: dict[tuple[int, str], dict[str, list[str]]] = {}
    requirement_candidates: dict[
        tuple[int, str], dict[str, list[str]]
    ] = {}
    for item in observations:
        line = item.get("line")
        kind = item.get("kind")
        function = item.get("function")
        if not line or kind not in {"parameter", "return"}:
            continue
        if kind == "return":
            function = function or item.get("name")
        if not function:
            continue
        # Successor observations retain the semantic qualified callable name
        # (for example ``PaperQAEnvironment.__init__``), while the source
        # annotation adapter addresses a definition by its source-local name
        # and line.  The line retains the necessary disambiguation; preserving
        # the qualifier here prevents every method parameter from matching its
        # FunctionDef.
        function = str(function).rsplit(".", 1)[-1]
        slot = "return" if kind == "return" else f"param:{item.get('name')}"
        values = [
            _successor_annotation(value)
            for value in item.get("types", [])
            if value
        ]
        target = (
            requirement_candidates
            if item.get("family") == "CallableTypeCandidates"
            else candidates
        )
        target.setdefault((int(line), function), {}).setdefault(
            slot, []
        ).extend(values)

    rendered: dict[tuple[int, str], dict[str, Any]] = {}
    for key in candidates.keys() | requirement_candidates.keys():
        observed_slots = candidates.get(key, {})
        fallback_slots = requirement_candidates.get(key, {})
        slots = {
            slot: observed_slots.get(slot) or fallback_slots.get(slot, [])
            for slot in observed_slots.keys() | fallback_slots.keys()
        }
        params = {
            slot.removeprefix("param:"): merged
            for slot, values in slots.items()
            if slot.startswith("param:") and (merged := _merge_types(values))
        }
        ret = _merge_types(slots.get("return", []))
        rendered[key] = {"params": params, "return": ret}
        if trace:
            for slot, values in slots.items():
                fallback = (
                    "no inferred return candidate"
                    if slot == "return"
                    else "no inferred parameter candidate"
                )
                trace.add_slot(
                    line=key[0], function=key[1], slot=slot,
                    candidates=[{
                        "successor_types": values,
                        **({"fallback_reasons": [fallback]}
                           if not values else {}),
                    }],
                    merged_annotation=(ret if slot == "return" else params.get(slot.removeprefix("param:"))),
                )
    return rendered


def _successor_variable_types(
    observations: list[dict[str, Any]], trace: _TraceBuffer | None = None,
    *, class_fields_only: bool = False,
) -> dict[tuple[int, str], str]:
    """Render diagram-produced store/attribute facts for source emission."""

    candidates: dict[tuple[int, str], list[str]] = {}
    for item in observations:
        line = item.get("line")
        name = item.get("name")
        if not line or item.get("kind") != "variable" or not name:
            continue
        if class_fields_only and (
            item.get("function") is not None
            or "." not in str(name)
            or item.get("family") != "ClassFieldTypeOf"
        ):
            continue
        # Class-attribute observations retain their qualified semantic name
        # (``Model.field``); source position plus the local target name is the
        # adapter identity. Instance targets likewise end in the attribute
        # name. Analysis itself continues to use the full semantic identity.
        local_name = str(name).rsplit(".", 1)[-1]
        values = [
            _successor_annotation(value)
            for value in item.get("types", [])
            if value
        ]
        candidates.setdefault((int(line), local_name), []).extend(values)

    rendered = {
        key: merged
        for key, values in candidates.items()
        if (merged := _merge_types(values))
    }
    if trace:
        for (line, name), values in candidates.items():
            trace.add_slot(
                line=line,
                function=str(next((
                    item.get("function") or "<module>"
                    for item in observations
                    if item.get("kind") == "variable"
                    and item.get("line") == line
                    and str(item.get("name", "")).rsplit(".", 1)[-1] == name
                ), "<module>")),
                slot=f"variable:{name}",
                candidates=[{"successor_types": values}],
                merged_annotation=rendered.get((line, name)),
            )
    return rendered


def _successor_annotation(value: str) -> str:
    if value == "builtins.NoneType":
        return "None"
    if value == "builtins.callable":
        return "Callable"
    return value.removeprefix("builtins.")


def _observation_admission_group(session, root_address) -> tuple[object, str]:
    """Group exact observations only by their owning callable boundary."""

    body_id = session.observation_workload_body_id(root_address)
    if body_id is None:
        return ("unowned", root_address.id)
    return ("callable", body_id)


def _run_successor_repo_probe(
    *,
    engine_worktree: Path,
    source_root: Path,
    runner: tuple[str, ...],
    timeout: int,
    progress_log: Path | None = None,
    demand_limit: int | None = None,
    checkpoint_roots: bool = False,
    checkpoint_size: int = 1,
    checkpoint_tail_start: int | None = None,
    checkpoint_tail_count: int | None = None,
    checkpoint_batch_start: int | None = None,
    checkpoint_batch_count: int | None = None,
    checkpoint_replay_prefix: bool = True,
    body_label: str | None = None,
    body_labels: tuple[str, ...] | None = None,
    root_ids: tuple[str, ...] | None = None,
    body_timeout: int | None = None,
    progress_timeout: int | None = None,
    sample_rate_hz: float | None = None,
    sample_body_label: str | None = None,
    sample_forward: bool = False,
    sample_session_open: bool = False,
    session_open_timeout: int | None = None,
    run_forward_seed: bool = True,
    forward_timeout: int | None = None,
    record_timings: bool = False,
    diagnostic_details: bool = True,
    collect_predictions: bool = True,
    observation_kinds: frozenset[str] = frozenset((
        "parameter", "return",
    )),
    disable_cyclic_gc: bool = True,
) -> dict[str, Any]:
    """Run one successor session for the complete repository source graph."""

    if (
        body_timeout is not None
        and body_label is None
        and not body_labels
        and sample_body_label is None
        and not checkpoint_roots
    ):
        raise ValueError(
            "body_timeout requires a selected body or checkpointed roots"
        )
    if progress_timeout is not None and progress_timeout <= 0:
        raise ValueError("progress_timeout must be positive")
    if checkpoint_size <= 0:
        raise ValueError("checkpoint_size must be positive")
    if checkpoint_tail_start is not None and checkpoint_tail_start < 0:
        raise ValueError("checkpoint_tail_start must be non-negative")
    if checkpoint_tail_count is not None and checkpoint_tail_count <= 0:
        raise ValueError("checkpoint_tail_count must be positive")
    if checkpoint_batch_start is not None and checkpoint_batch_start < 0:
        raise ValueError("checkpoint_batch_start must be non-negative")
    if checkpoint_batch_count is not None and checkpoint_batch_count <= 0:
        raise ValueError("checkpoint_batch_count must be positive")
    if checkpoint_batch_count is not None and checkpoint_batch_start is None:
        raise ValueError("checkpoint_batch_count requires checkpoint_batch_start")
    if checkpoint_tail_start is not None and checkpoint_batch_start is not None:
        raise ValueError("root-tail and batch-tail checkpoints are exclusive")
    if sample_rate_hz is not None and sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    if sample_body_label is not None and sample_rate_hz is None:
        raise ValueError("sample_body_label requires sample_rate_hz")
    if sample_forward and sample_rate_hz is None:
        raise ValueError("sample_forward requires sample_rate_hz")
    if session_open_timeout is not None and session_open_timeout <= 0:
        raise ValueError("session_open_timeout must be positive")
    if forward_timeout is not None and forward_timeout <= 0:
        raise ValueError("forward_timeout must be positive")
    unsupported_observation_kinds = observation_kinds - {
        "parameter", "return", "variable",
    }
    if unsupported_observation_kinds:
        raise ValueError(
            "unsupported observation kinds: "
            + ", ".join(sorted(unsupported_observation_kinds))
        )

    engine_worktree = Path(engine_worktree).resolve()
    probe = r'''
import gc
import json
import os
import signal
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

from sd_core.analysis.diagram_analysis import open_hybrid_program_session
from sd_core.tooling.analysis_arena import AnalysisAllocationArena
from sd_core.tooling.harness import TranslationResult

root = Path(sys.argv[1])
demand_limit = int(sys.argv[2]) or None
checkpoint_roots = sys.argv[3] == "checkpoint"
requested_body_label = sys.argv[4] or None
requested_body_labels = frozenset(json.loads(requested_body_label)) if requested_body_label else frozenset()
requested_body_timeout = int(sys.argv[5]) or None
sample_rate_hz = float(sys.argv[6]) or None
sample_body_label = sys.argv[7] or None
record_timings = sys.argv[8] == "timings"
diagnostic_details = sys.argv[9] == "diagnostics"
collect_predictions = sys.argv[10] == "predictions"
checkpoint_size = int(sys.argv[11])
checkpoint_tail_start = int(sys.argv[12])
checkpoint_tail_count = int(sys.argv[13])
requested_observation_kinds = frozenset(
    item for item in sys.argv[14].split(",") if item
)
sample_forward = sys.argv[15] == "sample-forward"
requested_forward_timeout = int(sys.argv[16]) or None
disable_cyclic_gc = sys.argv[17] == "disable-cyclic-gc"
checkpoint_replay_prefix = sys.argv[18] == "replay-prefix"
run_forward_seed = sys.argv[19] == "run-forward-seed"
sample_session_open = sys.argv[20] == "sample-session-open"
checkpoint_batch_start = int(sys.argv[21])
checkpoint_batch_count = int(sys.argv[22])
requested_progress_timeout = int(sys.argv[23]) or None
requested_root_ids = frozenset(json.loads(sys.argv[24]))
requested_session_open_timeout = int(sys.argv[25]) or None

# Repository sessions intentionally retain a large immutable scheduler/store
# graph.  Cyclic-GC pauses can therefore masquerade as semantic work whose
# cost grows with unrelated prior cohorts.  Attribute those pauses without a
# per-call profiler hook; this callback runs only at collection boundaries.
gc_started = {}
gc_totals = [
    {"collections": 0, "seconds": 0.0, "max_seconds": 0.0,
     "collected": 0, "uncollectable": 0}
    for _generation in range(3)
]

def gc_profile_callback(phase, info):
    generation = int(info.get("generation", 0))
    if generation >= len(gc_totals):
        return
    if phase == "start":
        gc_started[generation] = time.perf_counter()
        return
    started = gc_started.pop(generation, None)
    seconds = time.perf_counter() - started if started is not None else 0.0
    totals = gc_totals[generation]
    totals["collections"] += 1
    totals["seconds"] += seconds
    totals["max_seconds"] = max(totals["max_seconds"], seconds)
    totals["collected"] += int(info.get("collected", 0))
    totals["uncollectable"] += int(info.get("uncollectable", 0))

gc.callbacks.append(gc_profile_callback)
analysis_arena = None

def gc_profile_snapshot():
    return tuple(dict(item) for item in gc_totals)

def gc_profile_delta(before, after):
    return [
        {
            name: (
                current[name] - previous[name]
                if name != "max_seconds" else current[name]
            )
            for name in current
        }
        for previous, current in zip(before, after)
    ]

def analysis_source_roots():
    # Respect Python's conventional src layout.  Repository-wide prediction
    # output still copies every Python file, but the persistent program
    # session must model importable application modules rather than unrelated
    # profiling fixtures, examples, and release scripts.  When no src layout
    # exists, retain root modules and top-level package trees.
    src = root / "src"
    if src.is_dir() and any(src.rglob("*.py")):
        # Root-level importable modules (for example ``setup.py``) and the
        # conventional ``src`` tree are both analysis surfaces. Keep both
        # roots and let module-name resolution select the most specific one.
        return (root, src)
    package_roots = tuple(sorted(
        path for path in root.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    ))
    return (root,) if not package_roots else (root, *package_roots)

def analysis_paths():
    roots = analysis_source_roots()
    if roots == (root,):
        return tuple(sorted(root.rglob("*.py")))
    paths = set(root.glob("*.py"))
    for source_root in roots:
        if source_root != root:
            paths.update(source_root.rglob("*.py"))
    return tuple(sorted(paths))

source_roots = analysis_source_roots()

def module_name(path):
    # Traversal roots are not necessarily Python import roots.  A top-level
    # package such as ``root/capa`` is traversed directly to exclude unrelated
    # repository trees, but its import name must remain ``capa.*``.  Only a
    # conventional ``src`` directory is removed from the import identity.
    src_root = root / "src"
    source_root = (
        src_root
        if src_root.is_dir() and path.is_relative_to(src_root)
        else root
    )
    rel = path.relative_to(source_root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or "__init__"

def bounded_scheduler_snapshot(session):
    """Retain monotone progress counters even when a diagnostic cutoff fires."""
    scheduler = session.scheduler
    graph = scheduler.graph
    factored = scheduler._factored_telemetry.summary()
    def largest(mapping, limit=30):
        return dict(sorted(
            mapping.items(), key=lambda item: (-item[1], item[0])
        )[:limit])
    return {
        "topology_generation": graph.topology_generation,
        "unique_production_count": scheduler.unique_production_count,
        "production_execution_count": scheduler.production_execution_count,
        "repeated_production_count": scheduler.repeated_production_count,
        "production_executions_by_family": largest(
            scheduler._production_executions_by_family
        ),
        "production_repeats_by_family": largest(
            scheduler._production_repeats_by_family
        ),
        "production_seconds_by_family": largest(
            scheduler._production_seconds_by_family
        ),
        "worklist_schedule_counts": largest(
            scheduler._worklist_schedule_counts
        ),
        "knowledge_commit_counts": largest(
            scheduler.store.commit_counts
        ),
        "factored_phases": {
            key: factored[key]
            for key in (
                "factored_phase_counts",
                "factored_phase_seconds",
                "factored_rebase_outcome_counts",
                "factored_rebase_outcome_seconds",
                "factored_admission_size_counts",
                "factored_topology_refresh_size_counts",
                "factored_topology_refresh_delta_counts",
                "factored_max_admitted_productions",
                "factored_max_admitted_components",
            )
        },
        "topology_change_counts": largest(graph.topology_change_counts),
        "component_recompute_count": graph.component_recompute_count,
        "component_node_visits": graph.component_node_visits,
        "component_edge_visits": graph.component_edge_visits,
        "component_incremental_refresh_count": (
            graph.component_incremental_refresh_count
        ),
    }

try:
    phase_started = time.monotonic()
    all_paths = sorted(root.rglob("*.py"))
    paths = analysis_paths()
    by_module = {module_name(path): path for path in paths}
    module_files = {name: str(path.relative_to(root)) for name, path in by_module.items()}
    sources = {name: path.read_text(encoding="utf-8") for name, path in by_module.items()}
    modules = {}
    translation_failures = {}
    for name, source in sources.items():
        rel_name = module_files[name]
        print(
            f"ARCHWAY_TRANSLATION_START {rel_name}",
            file=sys.stderr, flush=True,
        )
        file_translation_started = time.monotonic()
        try:
            modules[name] = TranslationResult.from_source(
                source, name=name
            ).morphism
        except Exception as exc:
            translation_failures[module_files[name]] = (
                f"{type(exc).__name__}: {exc}"
            )
        print(
            "ARCHWAY_TRANSLATION_DONE "
            f"{time.monotonic() - file_translation_started:.6f} "
            f"{'failed' if rel_name in translation_failures else 'ok'} "
            f"{rel_name}",
            file=sys.stderr, flush=True,
        )
    if not modules:
        raise RuntimeError("no repository module translated successfully")
    translation_seconds = time.monotonic() - phase_started
    print(f"ARCHWAY_PHASE translation {translation_seconds:.6f}", file=sys.stderr, flush=True)
    entry = next(
        (name for name in ("main", "__main__") if name in modules),
        min(modules, key=lambda name: (name.count("."), len(name), name)),
    )
    session_profiler = None
    if sample_session_open:
        from sd_core.tooling.sampling_profile import SamplingProfiler
        session_profiler = SamplingProfiler(
            rate_hz=sample_rate_hz or 100.0,
            project_marker="/sd_core/",
        )
        session_profiler.__enter__()
    if requested_session_open_timeout:
        def timeout_session_open(_signum, _frame):
            raise TimeoutError("diagnostic session-open cutoff")
        signal.signal(signal.SIGALRM, timeout_session_open)
        signal.alarm(requested_session_open_timeout)
    session_sampling_profile = None
    try:
        session = open_hybrid_program_session(
            modules, entry, record_events=False,
            record_timings=record_timings,
            record_telemetry=diagnostic_details,
            # Retain an explicit benchmark-only equivalence oracle while the
            # hierarchical region worklist is being validated. Production
            # analysis defaults to the new ordering; setting this variable to
            # ``0`` asks the same engine revision to use its flat deque.
            hierarchical_region_worklist=(
                os.environ.get(
                    "ARCHWAY_HIERARCHICAL_REGION_WORKLIST", "1"
                ) != "0"
            ),
            # TypyBench observes a repository as an importable library surface;
            # it does not identify an executable entry point.  Keep one root
            # for bulk import seeding, but bind every module's ``__name__`` to
            # its qualified import name.  Treating an arbitrary shallow module
            # as ``__main__`` executes CLI guards and admits an unrelated whole
            # application call graph into signature inference.
            possible_entry_modules=frozenset(),
            # TypyBench requests callable signatures and class fields rather
            # than an executable-entry trace.  Select that observation policy
            # through the public restored runtime contract; class-field
            # templates are part of the ordinary diagram catalog.
            signature_observations_only=True,
        )
    finally:
        signal.alarm(0)
        if session_profiler is not None:
            session_profiler.__exit__(None, None, None)
            session_sampling_profile = session_profiler.jsonable(
                top=40, include_stacks=diagnostic_details
            )
            print(
                "ARCHWAY_SESSION_PROFILE " + json.dumps(
                    session_sampling_profile,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
    session_open_seconds = time.monotonic() - phase_started
    print(f"ARCHWAY_PHASE session_open {session_open_seconds:.6f}", file=sys.stderr, flush=True)
    if disable_cyclic_gc:
        # Translation/session construction creates temporary cyclic objects
        # that are not part of the persistent semantic graph.  Collect those
        # once, then make the forward/refinement lifetime the explicit arena.
        analysis_arena = AnalysisAllocationArena.enter_isolated_process(
            collect_on_enter=True
        )
    # Seed the selected program entry in the persistent scheduler.  Every
    # module is translated and available for later demands, but treating every
    # library module as an eager entry point creates a monolithic execution
    # wave.  The observation workload below extends this same fact store and
    # topology with only the additional module/body roots it actually needs.
    sampling_profile = None
    forward_profiler = None
    timed_out_forward = False
    if sample_forward:
        from sd_core.tooling.sampling_profile import SamplingProfiler
        forward_profiler = SamplingProfiler(
            rate_hz=sample_rate_hz,
            project_marker="/sd_core/",
        )
        forward_profiler.__enter__()
    if requested_forward_timeout:
        def timeout_forward(_signum, _frame):
            raise TimeoutError("diagnostic forward cutoff")
        signal.signal(signal.SIGALRM, timeout_forward)
        signal.alarm(requested_forward_timeout)
    try:
        # TypyBench requests repository-wide type observations.  Seed those
        # observations as one shared reduced-product wave; backward relevance
        # admits concrete/control/call coordinates when type production needs
        # them, without eagerly evaluating the full executable product.
        forward = (
            session.run_analysis_roots(include_callable_bodies=True)
            if run_forward_seed else None
        )
    except TimeoutError:
        timed_out_forward = True
        raise
    finally:
        signal.alarm(0)
        if forward_profiler is not None:
            forward_profiler.__exit__(None, None, None)
            sampling_profile = forward_profiler.jsonable(
                top=40, include_stacks=diagnostic_details
            )
    forward_seconds = time.monotonic() - phase_started
    print(f"ARCHWAY_PHASE forward {forward_seconds:.6f}", file=sys.stderr, flush=True)
    observations = session.type_observations()
    missing_observations = sorted((
        item for item in observations
        if item.kind in requested_observation_kinds
        if (session.store.resolved(item.address) is None
            or not session.store.resolved(item.address).value)
    ), key=lambda item: (
        item.module.dotted if item.module else "",
        item.function or "",
        item.position.row if item.position else -1,
        item.position.col if item.position else -1,
        item.kind,
        item.name,
        item.address.context,
    ))
    missing = tuple(dict.fromkeys(
        item.address for item in missing_observations
    ))
    all_signature_root_count = len({
        (
            "callable",
            session.observation_workload_body_id(address),
        )
        if session.observation_workload_body_id(address) is not None
        else ("fact", address.id)
        for address in missing
    })
    print(f"ARCHWAY_PHASE signature_demands {len(missing)}", file=sys.stderr, flush=True)
    body_labels = {
        template.body_morphism_id: (
            f"{template.module.dotted if template.module else '?'}:"
            f"{template.function or template.name}"
        )
        for plan in session.module_plans.values()
        for template in plan.templates
    }
    if requested_body_labels:
        available_body_labels = {
            body_labels.get(session.observation_workload_body_id(address), "?")
            for address in missing
            if session.observation_workload_body_id(address) is not None
        }
        unmatched_body_labels = requested_body_labels - available_body_labels
        if unmatched_body_labels:
            related_labels = sorted(
                label for label in available_body_labels
                if any(
                    requested.rsplit(":", 1)[-1].rsplit(".", 1)[-1]
                    in label
                    for requested in unmatched_body_labels
                )
            )[:20]
            raise ValueError(
                "requested callable body labels were not present in the "
                "observation workload: "
                + ", ".join(sorted(unmatched_body_labels))
                + (
                    "; related labels: " + ", ".join(related_labels)
                    if related_labels else ""
                )
            )
        requested = tuple(
            address for address in missing
            if body_labels.get(session.observation_workload_body_id(address))
            in requested_body_labels
        )
    else:
        requested = missing[:demand_limit] if demand_limit is not None else missing
    # The native workload above already performs collective targeted waves for
    # every supported observation in the persistent session.  Anything still
    # unresolved is either an explicit native bottom or a superseded
    # uninvoked-body view for which a contextual body instance exists.  Do not
    # reinterpret those outcomes as requests for the removed coarse
    # body-summary runtime.
    signature_roots = ()
    print(f"ARCHWAY_PHASE body_roots {len(signature_roots)}", file=sys.stderr, flush=True)
    if diagnostic_details and len(signature_roots) <= 32:
        print(
            "ARCHWAY_ROOTS " + json.dumps([
                body_labels.get(
                    session.observation_workload_body_id(item), "?"
                )
                for item in signature_roots
            ]),
            file=sys.stderr,
            flush=True,
        )
    targeted_profiler = None
    if (
        sample_rate_hz
        and not sample_forward
        and sample_body_label is None
        and signature_roots
    ):
        from sd_core.tooling.sampling_profile import SamplingProfiler
        targeted_profiler = SamplingProfiler(
            rate_hz=sample_rate_hz,
            project_marker="/sd_core/",
        )
        targeted_profiler.__enter__()
    timed_out_body = False
    timed_out_execution = None
    timeout_signal = signal.SIGALRM
    if requested_body_timeout:
        def timeout_body(_signum, _frame):
            raise TimeoutError("diagnostic body cutoff")
        signal.signal(timeout_signal, timeout_body)
    if requested_progress_timeout:
        session.scheduler.set_execution_progress_tracking(True)

        def timeout_stalled_execution(_signum, _frame):
            global timed_out_execution
            progress = dict(session.scheduler.execution_progress)
            elapsed = max(
                float(progress.get("active_seconds", 0.0)),
                float(progress.get("seconds_since_progress", 0.0)),
            )
            if elapsed >= requested_progress_timeout:
                timed_out_execution = progress
                raise TimeoutError("scheduler execution progress cutoff")
            signal.alarm(max(
                1,
                int(requested_progress_timeout - elapsed + 0.999999),
            ))

        signal.signal(timeout_signal, timeout_stalled_execution)
    if checkpoint_roots:
        targeted = None
        body_profiles = []
        # Public roots retain exact observation identity.  Group observations
        # by the diagram callable that owns their shared workload, then admit
        # one callable group per convergence wave.  The session creates the
        # internal shared carrier; the adapter must not infer it from a public
        # root subject or mix unrelated callable groups by an arbitrary size.
        def admission_group(root_address):
            body_id = session.observation_workload_body_id(root_address)
            if body_id is None:
                return ("unowned", root_address.id)
            return ("callable", body_id)

        def admission_batches(roots):
            grouped = {}
            for root_address in roots:
                group = admission_group(root_address)
                grouped.setdefault(group, []).append(root_address)
            return tuple(tuple(items) for items in grouped.values())
        all_batches = admission_batches(signature_roots)
        requested_tail_start = (
            min(checkpoint_tail_start, len(signature_roots))
            if checkpoint_tail_start >= 0 else 0
        )
        prefix = (
            admission_batches(signature_roots[:requested_tail_start])
            if checkpoint_tail_start >= 0 and checkpoint_replay_prefix else ()
        )
        # A no-prefix tail is an explicit diagnostic slice: it identifies hot
        # later roots without pretending to measure the reuse accumulated by
        # the complete persistent session. Production and acceptance runs
        # retain prefix replay or execute the full root sequence directly.
        tail_start = requested_tail_start
        tail_end = (
            min(len(signature_roots), tail_start + checkpoint_tail_count)
            if checkpoint_tail_count > 0 else len(signature_roots)
        )
        if checkpoint_batch_start >= 0:
            batch_start = min(checkpoint_batch_start, len(all_batches))
            batch_end = (
                min(len(all_batches), batch_start + checkpoint_batch_count)
                if checkpoint_batch_count > 0 else len(all_batches)
            )
            root_batches = (
                all_batches[:batch_start]
                if checkpoint_replay_prefix else ()
            ) + all_batches[batch_start:batch_end]
        else:
            root_batches = prefix + (
                tuple((root,) for root in signature_roots[tail_start:tail_end])
                if checkpoint_tail_start >= 0
                else all_batches
            )
        print(
            "ARCHWAY_BODY_PLAN " + json.dumps([[
                body_labels.get(
                    session.observation_workload_body_id(root), "?"
                )
                for root in root_batch
            ]
                for root_batch in root_batches
            ], separators=(",", ":")),
            file=sys.stderr,
            flush=True,
        )
        for index, root_batch in enumerate(root_batches, 1):
            root_address = root_batch[0]
            body_started = time.monotonic()
            executions_before = session.scheduler.production_execution_count
            topology_before = session.scheduler.graph.topology_generation
            edge_telemetry_before = dict(
                session.scheduler.graph.component_edge_update_telemetry
            )
            topology_counts_before = dict(
                session.scheduler.graph.topology_change_counts
            )
            gc_before = gc_profile_snapshot()
            telemetry_before = (
                session.scheduler.production_family_telemetry
                if diagnostic_details else None
            )
            families_before = (
                telemetry_before["executions"] if telemetry_before else {}
            )
            family_seconds_before = (
                telemetry_before["seconds"] if telemetry_before else {}
            )
            transfer_counts_before = (
                dict(session.scheduler.transfer_operation_counts)
                if diagnostic_details else {}
            )
            transfer_seconds_before = (
                dict(session.scheduler.transfer_operation_seconds)
                if diagnostic_details else {}
            )
            production_operation_before = (
                session.scheduler.production_operation_telemetry
                if diagnostic_details else {"executions": {}, "seconds": {}}
            )
            production_phase_before = (
                session.scheduler.production_phase_telemetry
                if diagnostic_details else {"counts": {}, "seconds": {}}
            )
            body_id = session.observation_workload_body_id(root_address)
            body_label = body_labels.get(body_id, "?")
            print(
                f"ARCHWAY_BODY_START {index}/{len(root_batches)} "
                f"{body_label} {root_address.id}",
                file=sys.stderr, flush=True,
            )
            sample_this_body = (
                sample_rate_hz and body_label == sample_body_label
            )
            cutoff_this_body = (
                requested_body_timeout
                and (
                    (
                        not requested_body_labels
                        and sample_body_label is None
                    )
                    or
                    body_label == sample_body_label
                    or body_label in requested_body_labels
                )
            )
            profiler = None
            if cutoff_this_body:
                signal.alarm(requested_body_timeout)
            try:
                if sample_this_body:
                    from sd_core.tooling.sampling_profile import SamplingProfiler
                    profiler = SamplingProfiler(
                        rate_hz=sample_rate_hz,
                        project_marker="/sd_core/",
                    )
                    profiler.__enter__()
                targeted = session.observe_workload(root_batch)
            except TimeoutError:
                timed_out_body = True
                if timed_out_execution is None and requested_progress_timeout:
                    timed_out_execution = dict(
                        session.scheduler.execution_progress
                    )
                targeted = None
            finally:
                signal.alarm(0)
                if profiler is not None:
                    profiler.__exit__(None, None, None)
                    sampling_profile = profiler.jsonable(
                        top=40, include_stacks=diagnostic_details
                    )
            telemetry_after = (
                session.scheduler.production_family_telemetry
                if diagnostic_details else {"executions": {}, "seconds": {}}
            )
            family_deltas = {
                family: count - families_before.get(family, 0)
                for family, count in telemetry_after["executions"].items()
                if count - families_before.get(family, 0) > 0
            }
            family_second_deltas = {
                family: seconds - family_seconds_before.get(family, 0.0)
                for family, seconds in telemetry_after["seconds"].items()
                if seconds - family_seconds_before.get(family, 0.0) > 0
            }
            transfer_count_deltas = {
                operation: count - transfer_counts_before.get(operation, 0)
                for operation, count in (
                    session.scheduler.transfer_operation_counts.items()
                )
                if count - transfer_counts_before.get(operation, 0) > 0
            } if diagnostic_details else {}
            transfer_second_deltas = {
                operation: seconds - transfer_seconds_before.get(
                    operation, 0.0
                )
                for operation, seconds in (
                    session.scheduler.transfer_operation_seconds.items()
                )
                if seconds - transfer_seconds_before.get(operation, 0.0) > 0
            } if diagnostic_details else {}
            production_operation_after = (
                session.scheduler.production_operation_telemetry
                if diagnostic_details else {"executions": {}, "seconds": {}}
            )
            production_operation_deltas = {
                operation: count - production_operation_before[
                    "executions"
                ].get(operation, 0)
                for operation, count in production_operation_after[
                    "executions"
                ].items()
                if count - production_operation_before["executions"].get(
                    operation, 0
                ) > 0
            }
            production_operation_second_deltas = {
                operation: seconds - production_operation_before[
                    "seconds"
                ].get(operation, 0.0)
                for operation, seconds in production_operation_after[
                    "seconds"
                ].items()
                if seconds - production_operation_before["seconds"].get(
                    operation, 0.0
                ) > 0
            }
            production_phase_after = (
                session.scheduler.production_phase_telemetry
                if diagnostic_details else {"counts": {}, "seconds": {}}
            )
            production_phase_count_deltas = {
                label: count - production_phase_before["counts"].get(label, 0)
                for label, count in production_phase_after["counts"].items()
                if count - production_phase_before["counts"].get(label, 0) > 0
            }
            production_phase_second_deltas = {
                label: seconds - production_phase_before["seconds"].get(
                    label, 0.0
                )
                for label, seconds in production_phase_after["seconds"].items()
                if seconds - production_phase_before["seconds"].get(
                    label, 0.0
                ) > 0
            }
            workload_relevance = session.observation_workload_description(
                root_batch
            )
            body_profile = {
                "index": index,
                "label": body_label,
                "seconds": time.monotonic() - body_started,
                "executions": (
                    session.scheduler.production_execution_count
                    - executions_before
                ),
                "topology_changes": session.scheduler.graph.topology_generation - topology_before,
                "topology_change_counts": {
                    name: value - topology_counts_before.get(name, 0)
                    for name, value in (
                        session.scheduler.graph.topology_change_counts
                    ).items()
                },
                "component_edge_updates": {
                    name: value - edge_telemetry_before.get(name, 0)
                    for name, value in (
                        session.scheduler.graph.component_edge_update_telemetry
                    ).items()
                },
                "gc": gc_profile_delta(gc_before, gc_profile_snapshot()),
                "top_execution_families": sorted(
                    family_deltas.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:8],
                "top_family_seconds": sorted(
                    family_second_deltas.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:8],
                "top_transfer_operations": sorted(
                    transfer_count_deltas.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:12],
                "top_production_operations": sorted(
                    production_operation_deltas.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:12],
                "top_production_seconds": sorted(
                    production_operation_second_deltas.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:12],
                "top_production_phases": sorted(
                    production_phase_count_deltas.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:20],
                "top_production_phase_seconds": sorted(
                    production_phase_second_deltas.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:20],
                "top_transfer_seconds": sorted(
                    transfer_second_deltas.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:12],
                "workload_relevance": workload_relevance,
                "root_id": root_address.id,
                "root_ids": [item.id for item in root_batch],
                "root_labels": [
                    body_labels.get(
                        session.observation_workload_body_id(item), "?"
                    )
                    for item in root_batch
                ],
            }
            body_profiles.append(
                body_profile if diagnostic_details else {
                    "index": index,
                    "label": body_label,
                    # Cohorts are the actual unit of shared convergence.  A
                    # single leading label hid which companion demand caused
                    # a replay wave in low-overhead framework diagnostics.
                    "root_labels": body_profile["root_labels"],
                    "seconds": body_profile["seconds"],
                    "executions": body_profile["executions"],
                    "topology_changes": body_profile["topology_changes"],
                    "topology_change_counts": body_profile[
                        "topology_change_counts"
                    ],
                    "component_edge_updates": body_profile[
                        "component_edge_updates"
                    ],
                }
            )
            # One compact line per dependency-safe checkpoint is intentionally
            # retained in production-light runs. It survives a bounded
            # subprocess timeout, unlike the final JSON summary.
            print(
                f"ARCHWAY_BODY {index}/{len(root_batches)} "
                f"{body_profile['seconds']:.6f} "
                f"exec={body_profile['executions']} "
                f"topology={body_profile['topology_changes']} "
                f"{body_profile['label']}"
                + (f" {root_address.id}" if diagnostic_details else ""),
                file=sys.stderr, flush=True,
            )
            if diagnostic_details:
                print(
                    "ARCHWAY_BODY_DETAIL " + json.dumps({
                        "index": index,
                        "top_execution_families": body_profile[
                            "top_execution_families"
                        ],
                        "top_family_seconds": body_profile[
                            "top_family_seconds"
                        ],
                        "top_production_operations": body_profile[
                            "top_production_operations"
                        ],
                        "top_production_seconds": body_profile[
                            "top_production_seconds"
                        ],
                        "top_production_phases": body_profile[
                            "top_production_phases"
                        ],
                        "top_production_phase_seconds": body_profile[
                            "top_production_phase_seconds"
                        ],
                        "top_transfer_operations": body_profile[
                            "top_transfer_operations"
                        ],
                        "top_transfer_seconds": body_profile[
                            "top_transfer_seconds"
                        ],
                        "topology_change_counts": body_profile[
                            "topology_change_counts"
                        ],
                        "component_edge_updates": body_profile[
                            "component_edge_updates"
                        ],
                        "gc": body_profile["gc"],
                    }, separators=(",", ":")),
                    file=sys.stderr,
                    flush=True,
                )
            if timed_out_body:
                break
    else:
        body_profiles = []
        # SamplingProfiler owns ITIMER_VIRTUAL/SIGVTALRM.  Keep the bounded
        # body cutoff on the independent wall-clock alarm so both diagnostics
        # remain active when profiling one long-running body.
        collective_timeout = requested_progress_timeout or requested_body_timeout
        if collective_timeout and signature_roots:
            signal.alarm(collective_timeout)
        try:
            if (
                sample_rate_hz and signature_roots
                and targeted_profiler is None
            ):
                from sd_core.tooling.sampling_profile import SamplingProfiler
                profiler = SamplingProfiler(
                    rate_hz=sample_rate_hz,
                    project_marker="/sd_core/",
                )
                profiler.__enter__()
                try:
                    targeted = session.observe(signature_roots)
                finally:
                    profiler.__exit__(None, None, None)
                    sampling_profile = profiler.jsonable(
                        top=40, include_stacks=diagnostic_details
                    )
            else:
                targeted = session.observe(signature_roots) if signature_roots else None
                sampling_profile = None
        except TimeoutError:
            targeted = None
            timed_out_body = True
            if timed_out_execution is None and requested_progress_timeout:
                timed_out_execution = dict(
                    session.scheduler.execution_progress
                )
            sampling_profile = locals().get("sampling_profile")
        finally:
            signal.alarm(0)
    if targeted_profiler is not None:
        targeted_profiler.__exit__(None, None, None)
        sampling_profile = targeted_profiler.jsonable(
            top=40, include_stacks=diagnostic_details
        )
    targeted_seconds = time.monotonic() - phase_started
    print(f"ARCHWAY_PHASE targeted {targeted_seconds:.6f}", file=sys.stderr, flush=True)
    projection_started = time.monotonic()
    files = {}
    if collect_predictions:
        files = {str(path.relative_to(root)): [] for path in all_paths}
        for item in session.type_observations():
            module = item.module.dotted if item.module is not None else None
            rel = module_files.get(module)
            if rel is None and module is not None:
                matches = [path for name, path in module_files.items()
                           if module == name or module.endswith("." + name)]
                rel = matches[0] if len(matches) == 1 else None
            fact = session.store.resolved(item.address)
            if rel is None:
                continue
            files[rel].append({
                "line": item.position.row if item.position is not None else None,
                "name": item.name,
                "kind": item.kind,
                "family": item.address.family,
                "function": item.function,
                # Retain unresolved catalog entries as explicit missing
                # evidence.  The source adapter inserts nothing for an empty
                # set, while diagnostic traces can now distinguish an open
                # analysis result from an uncataloged source location.
                "types": (
                    sorted(str(value) for value in fact.value)
                    if fact is not None else []
                ),
            })
        for item, candidate in session.type_candidate_observations():
            # Nested-path candidates constrain an element/attribute reached
            # through the parameter, not the parameter annotation itself.
            if candidate.path or len(candidate.types) != 1:
                continue
            module = item.module.dotted if item.module is not None else None
            rel = module_files.get(module)
            if rel is None and module is not None:
                matches = [path for name, path in module_files.items()
                           if module == name or module.endswith("." + name)]
                rel = matches[0] if len(matches) == 1 else None
            if rel is None:
                continue
            files[rel].append({
                "line": (
                    item.position.row if item.position is not None else None
                ),
                "name": item.name,
                "kind": item.kind,
                "family": item.address.family,
                "function": item.function,
                "types": sorted(candidate.types),
                "precision": candidate.precision,
                "requirement_path": [],
            })
    observation_projection_seconds = time.monotonic() - projection_started
    scheduler_telemetry = (
        dict(session.scheduler.aggregate_production_telemetry)
        if diagnostic_details else bounded_scheduler_snapshot(session)
    )
    component_hotspots = (
        session.scheduler.component_hotspots()
        if diagnostic_details else ()
    )
    region_quotient_summary = (
        session.scheduler.region_quotient_summary()
        if diagnostic_details else {}
    )
    if component_hotspots:
        callable_labels = {
            body_id: f"{boundary.module_name}:{boundary.qualified_name}"
            for body_id, boundary
            in session.callable_boundaries_by_body.items()
        }
        native_context_labels = {
            admission.application.callee_context: callable_labels.get(
                admission.application.body_morphism_id,
                admission.application.body_morphism_id,
            )
            for admission in session.native_callable_cell_admissions()
        }
        native_context_labels.update({
            f"context:uninvoked-body:{body_id}": label
            for body_id, label in callable_labels.items()
        })
        component_hotspots = tuple({
            **item,
            "semantic_contexts": tuple({
                "context": context,
                "label": native_context_labels.get(context, context),
                "members": members,
            } for context, members in item.get("contexts", {}).items()),
        } for item in component_hotspots)
    scheduler_telemetry.pop("production_executions_by_provider", None)
    out = {
        "ok": True,
        "files": files,
        "analysis_summary": {
            "modules": len(modules),
            "observations": len(observations),
            "targeted_addresses": len(missing),
            "requested_addresses": len(requested),
            "requested_body_roots": len(signature_roots),
            "signature_body_roots": all_signature_root_count,
            "body_profiles": body_profiles,
            "timed_out_body": timed_out_body,
            "timed_out_execution": timed_out_execution,
            "forward_events": len(forward.events) if forward is not None else 0,
            "targeted_events": len(targeted.events) if targeted is not None else 0,
            "resolved_facts": (
                len(session.store.snapshot().resolved_facts)
                if diagnostic_details else None
            ),
            "translation_failures": translation_failures,
            "phase_seconds": {
                "translation": translation_seconds,
                "session_open": session_open_seconds - translation_seconds,
                "forward": forward_seconds - session_open_seconds,
                "targeted": targeted_seconds - forward_seconds,
                "observation_projection": observation_projection_seconds,
            },
            "scheduler": scheduler_telemetry,
            "component_hotspots": (
                component_hotspots
            ),
            "region_quotient_summary": region_quotient_summary,
            "gc": gc_profile_snapshot(),
            "production_replay_hotspots": (
                session.scheduler.production_replay_hotspots()
                if diagnostic_details else ()
            ),
            "production_replay_operation_hotspots": (
                session.scheduler.production_replay_operation_hotspots()
                if diagnostic_details else ()
            ),
            "sampling_profile": sampling_profile,
            "observation_modules": sorted({
                item.module.dotted for item in observations
                if item.module is not None
            }) if diagnostic_details else [],
            "module_plan_observations": {
                name: [len(plan.observations), len(plan.templates)]
                for name, plan in session.module_plans.items()
            } if diagnostic_details else {},
        },
    }
    out["analysis_summary"]["phase_seconds"]["result_assembly"] = (
        time.monotonic() - projection_started
        - observation_projection_seconds
    )
except Exception as exc:
    print(
        f"ARCHWAY_FAILURE {type(exc).__name__}: {exc}",
        file=sys.stderr,
        flush=True,
    )
    partial_summary = {}
    if "sampling_profile" in locals() and sampling_profile is not None:
        partial_summary["sampling_profile"] = sampling_profile
    if (
        "session_sampling_profile" in locals()
        and session_sampling_profile is not None
    ):
        partial_summary["session_sampling_profile"] = (
            session_sampling_profile
        )
    if "timed_out_forward" in locals():
        partial_summary["timed_out_forward"] = timed_out_forward
    if "translation_seconds" in locals():
        partial_summary.setdefault("phase_seconds", {})["translation"] = (
            translation_seconds
        )
    if "session_open_seconds" in locals():
        partial_summary.setdefault("phase_seconds", {})["session_open"] = (
            session_open_seconds - translation_seconds
        )
    if "session" in locals():
        partial_summary["scheduler"] = bounded_scheduler_snapshot(session)
    out = {
        "ok": False,
        "error": f"{type(exc).__name__}: {exc}",
        "trace_tail": traceback.format_exc()[-2400:],
        "analysis_summary": partial_summary,
    }
encode_started = time.monotonic()
encoded = json.dumps(out, sort_keys=True)
print(
    f"ARCHWAY_PHASE result_encode {time.monotonic() - encode_started:.6f}",
    file=sys.stderr,
    flush=True,
)
print(encoded)
sys.stdout.flush()
# This process is an isolated analysis worker and has no in-process resources
# that must outlive its serialized result.  Normal interpreter shutdown walks
# and decrefs the complete repository scheduler/store graph, which can add
# tens of seconds after the durable evidence is already on stdout.  Let the OS
# reclaim that graph at the process boundary instead.
os._exit(0)
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=True) as f:
        f.write(probe)
        f.flush()
        cmd = [
            *runner,
            f.name,
            str(Path(source_root).absolute()),
            str(demand_limit or 0),
            "checkpoint" if checkpoint_roots else "collective",
            json.dumps(tuple(dict.fromkeys((
                *((body_label,) if body_label else ()),
                *(body_labels or ()),
            )))),
            str(body_timeout or 0),
            str(sample_rate_hz or 0),
            sample_body_label or "",
            "timings" if record_timings else "no-timings",
            "diagnostics" if diagnostic_details else "compact",
            "predictions" if collect_predictions else "evidence-only",
            str(checkpoint_size),
            str(
                checkpoint_tail_start
                if checkpoint_tail_start is not None else -1
            ),
            str(checkpoint_tail_count or 0),
            ",".join(sorted(observation_kinds)),
            "sample-forward" if sample_forward else "no-forward-sample",
            str(forward_timeout or 0),
            "disable-cyclic-gc" if disable_cyclic_gc else "cyclic-gc",
            "replay-prefix" if checkpoint_replay_prefix else "skip-prefix",
            "run-forward-seed" if run_forward_seed else "skip-forward-seed",
            "sample-session-open" if sample_session_open else "no-session-sample",
            str(
                checkpoint_batch_start
                if checkpoint_batch_start is not None else -1
            ),
            str(checkpoint_batch_count or 0),
            str(progress_timeout or 0),
            json.dumps(tuple(dict.fromkeys(root_ids or ()))),
            str(session_open_timeout or 0),
        ]
        progress_stream = None
        if progress_log is not None:
            progress_log = Path(progress_log)
            progress_log.parent.mkdir(parents=True, exist_ok=True)
            progress_stream = progress_log.open("w", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                cmd, cwd=engine_worktree, stdout=subprocess.PIPE,
                stderr=(progress_stream if progress_stream is not None else subprocess.PIPE),
                text=True, env=_probe_env(engine_worktree),
                start_new_session=True,
            )
            try:
                stdout, captured_stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                _stdout, captured_stderr = proc.communicate()
                if progress_stream is not None:
                    progress_stream.flush()
                    stderr = progress_log.read_text(encoding="utf-8")
                else:
                    stderr = captured_stderr or ""
                return {
                    "ok": False,
                    "error": f"TimeoutExpired: analysis exceeded {timeout}s",
                    "trace_tail": stderr[-2400:],
                    "analysis_summary": _probe_progress(stderr),
                }
            except BaseException:
                # The worker owns a process group because a repository
                # analysis may itself be launched through Hatch.  Never leave
                # that group consuming CPU after an operator interrupts a
                # diagnostic or corpus gate.
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.communicate()
                raise
            if progress_stream is not None:
                progress_stream.flush()
                stderr = progress_log.read_text(encoding="utf-8")
            else:
                stderr = captured_stderr or ""
        finally:
            if progress_stream is not None:
                progress_stream.close()
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": f"engine probe failed: exit={proc.returncode}",
            "trace_tail": stderr[-2400:],
            "analysis_summary": _probe_progress(stderr),
        }
    for line in reversed(stdout.splitlines()):
        if line.strip().startswith("{"):
            result = json.loads(line)
            if not result.get("ok") and not result.get("analysis_summary"):
                result["analysis_summary"] = _probe_progress(stderr)
            return result
    return {"ok": False, "error": "engine probe produced no JSON", "trace_tail": stderr[-2400:]}


def _run_engine_probe(
    *,
    engine_worktree: Path,
    source_root: Path,
    runner: tuple[str, ...],
    timeout: int,
    per_file_timeout: int = 60,
    analysis_observation_mode: str = "summary",
) -> dict[str, Any]:
    out: dict[str, Any] = {"files": {}}
    started = time.monotonic()
    for path in sorted(Path(source_root).rglob("*.py")):
        rel = str(path.relative_to(source_root))
        elapsed = time.monotonic() - started
        remaining = timeout - elapsed
        if remaining <= 0:
            out["files"][rel] = {
                "ok": False,
                "error": f"TimeoutExpired: repo analysis exceeded {timeout}s",
            }
            continue
        out["files"][rel] = _run_engine_probe_file(
            engine_worktree=engine_worktree,
            source_path=path,
            module_name=path.stem,
            runner=runner,
            timeout=max(1, min(per_file_timeout, int(remaining))),
            analysis_observation_mode=analysis_observation_mode,
        )
    return out


def _run_engine_probe_file(
    *,
    engine_worktree: Path,
    source_path: Path,
    module_name: str,
    runner: tuple[str, ...],
    timeout: int,
    analysis_observation_mode: str = "summary",
) -> dict[str, Any]:
    probe = r'''
import json
import os
import sys
import traceback
from pathlib import Path

from sd_core.analysis_server import analyze_source

path = Path(sys.argv[1])
module_name = sys.argv[2]
try:
    source = path.read_text(encoding="utf-8")
    analysis = analyze_source(source, module_name)
    out = {
        "ok": True,
        "analysis": analysis,
        "analysis_summary": analysis.get("file_result", {}).get(
            "analysis_summary"
        ),
    }
except Exception as exc:
    out = {
        "ok": False,
        "error": f"{type(exc).__name__}: {exc}",
        "trace_tail": traceback.format_exc()[-1200:],
    }
print(json.dumps(out, sort_keys=True))
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=True) as f:
        f.write(probe)
        f.flush()
        source_path = Path(source_path)
        if not source_path.is_file():
            return {
                "ok": False,
                "error": f"FileNotFoundError: source file does not exist: {source_path}",
            }
        source_arg = source_path if source_path.is_absolute() else source_path.absolute()
        cmd = [*runner, f.name, str(source_arg), module_name]
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=engine_worktree,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=_probe_env(
                    engine_worktree,
                    analysis_observation_mode=analysis_observation_mode,
                ),
                start_new_session=True,
            )
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
            return {
                "ok": False,
                "error": f"TimeoutExpired: analysis exceeded {timeout}s",
                "trace_tail": ((stderr or "")[-1200:] if isinstance(stderr, str) else ""),
            }
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": f"engine probe failed: exit={proc.returncode}",
            "trace_tail": stderr[-1200:],
        }
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    return {
        "ok": False,
        "error": "engine probe produced no JSON",
        "trace_tail": stderr[-1200:],
    }


def _probe_env(
    engine_worktree: Path,
    *,
    analysis_observation_mode: str = "summary",
) -> dict[str, str]:
    env = os.environ.copy()
    env["ARCHWAY_ANALYSIS_OBSERVATION"] = analysis_observation_mode
    env.pop("ARCHWAY_BODY_SUMMARY_CONSUMPTION", None)
    env.pop("ARCHWAY_ANALYSIS_PRODUCT", None)
    env.pop("ARCHWAY_TYPE_REQUIREMENTS_ASSUME_CLOSED", None)
    existing = env.get("PYTHONPATH")
    paths = [str(engine_worktree)]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _trace_path_from_env() -> Path | None:
    value = os.environ.get(_TRACE_ENV_VAR)
    return Path(value) if value else None


class _TraceWriter:
    def __init__(self, path: Path, repo_name: str) -> None:
        self.path = Path(path)
        self.repo_name = repo_name
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")

    def for_file(self, file_name: str) -> "_TraceBuffer":
        return _TraceBuffer(self, file_name)

    def write(self, record: dict[str, Any]) -> None:
        payload = {"repo": self.repo_name, **record}
        self._handle.write(json.dumps(payload, sort_keys=True) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


class _ProfileWriter:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")

    def write(self, profile: FileProfile) -> None:
        self._handle.write(json.dumps(profile.to_json(), sort_keys=True) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


def capture_translation_trace_file(
    *,
    engine_worktree: Path,
    source_path: Path,
    module_name: str,
    trace_dir: Path,
    runner: tuple[str, ...] = ("hatch", "run", "python"),
    timeout: int = 60,
) -> dict[str, Any]:
    """Capture a human-readable translation trace for one source file.

    This is intentionally translation-only. It does not run analysis, so it can
    be applied after a profiling pass to slow or failed files without changing
    TypyBench scoring semantics.
    """

    source_path = Path(source_path)
    trace_dir = Path(trace_dir)
    rel_name = _safe_artifact_name(str(source_path.name))
    trace_txt = trace_dir / f"{rel_name}.trace.txt"
    summary_json = trace_dir / f"{rel_name}.trace-summary.json"
    trace_dir.mkdir(parents=True, exist_ok=True)

    record = _run_translation_trace_probe_file(
        engine_worktree=Path(engine_worktree),
        source_path=source_path,
        module_name=module_name,
        runner=runner,
        timeout=timeout,
    )
    text = record.pop("trace_text", None)
    if text is not None:
        trace_txt.write_text(text, encoding="utf-8")
        record["trace_text_path"] = str(trace_txt)
    summary_json.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    record["summary_path"] = str(summary_json)
    return record


def capture_runtime_phase_profile_file(
    *,
    engine_worktree: Path,
    source_path: Path,
    module_name: str,
    runner: tuple[str, ...] = ("hatch", "run", "python"),
    timeout: int = 90,
) -> dict[str, Any]:
    """Measure import, translation, traced translation, and analysis separately.

    Each phase runs in its own subprocess. This keeps a stuck analysis/fixpoint
    from hiding whether translation or trace capture was fast.
    """

    source_path = Path(source_path)
    out: dict[str, Any] = {"file": str(source_path), "module_name": module_name}
    for phase in (
        "import_only",
        "translation_no_trace",
        "translation_trace",
        "analyze_source",
    ):
        out[phase] = _run_runtime_phase_probe_file(
            engine_worktree=Path(engine_worktree),
            source_path=source_path,
            module_name=module_name,
            runner=runner,
            timeout=timeout,
            phase=phase,
        )
    return out


def _run_runtime_phase_probe_file(
    *,
    engine_worktree: Path,
    source_path: Path,
    module_name: str,
    runner: tuple[str, ...],
    timeout: int,
    phase: str,
) -> dict[str, Any]:
    probe = r'''
import json
import os
import sys
import time
import traceback
from pathlib import Path

phase = sys.argv[1]
path = Path(sys.argv[2])
module_name = sys.argv[3]
started = time.monotonic()
out = {"ok": False, "phase": phase}
try:
    from sd_core.tooling.harness import TranslationResult
    from sd_core.analysis_server import analyze_source
    if phase == "import_only":
        out = {"ok": True, "phase": phase}
    else:
        source = path.read_text(encoding="utf-8")
        if phase == "translation_no_trace":
            result = TranslationResult.from_source(source, trace=False, name=module_name)
            out = {
                "ok": True,
                "phase": phase,
                "morphism_kind": type(result.morphism).__name__,
            }
        elif phase == "translation_trace":
            result = TranslationResult.from_source(source, trace=True, name=module_name)
            trace = result.traces[0] if result.traces else None
            out = {
                "ok": True,
                "phase": phase,
                "trace_count": len(result.traces),
                "span_count": len(getattr(trace, "spans", [])) if trace is not None else 0,
            }
        elif phase == "analyze_source":
            result = analyze_source(source, module_name)
            out = {
                "ok": True,
                "phase": phase,
                "function_count": len(result.get("functions", [])) if isinstance(result, dict) else None,
            }
        else:
            raise RuntimeError(f"unknown runtime phase: {phase}")
except Exception as exc:
    out = {
        "ok": False,
        "phase": phase,
        "error": f"{type(exc).__name__}: {exc}",
        "trace_tail": traceback.format_exc()[-2000:],
    }
out["seconds"] = round(time.monotonic() - started, 6)
print(json.dumps(out, sort_keys=True))
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=True) as f:
        f.write(probe)
        f.flush()
        cmd = [*runner, f.name, phase, str(source_path.resolve()), module_name]
        started = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=engine_worktree,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=_probe_env(engine_worktree),
                start_new_session=True,
            )
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
            return {
                "ok": False,
                "phase": phase,
                "seconds": round(time.monotonic() - started, 6),
                "error": f"TimeoutExpired: {phase} exceeded {timeout}s",
                "trace_tail": ((stderr or "")[-2000:] if isinstance(stderr, str) else ""),
            }
    if proc.returncode != 0:
        return {
            "ok": False,
            "phase": phase,
            "seconds": round(time.monotonic() - started, 6),
            "error": f"runtime phase probe failed: exit={proc.returncode}",
            "trace_tail": stderr[-2000:],
        }
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    return {
        "ok": False,
        "phase": phase,
        "seconds": round(time.monotonic() - started, 6),
        "error": "runtime phase probe produced no JSON",
        "trace_tail": stderr[-2000:],
    }


def _run_translation_trace_probe_file(
    *,
    engine_worktree: Path,
    source_path: Path,
    module_name: str,
    runner: tuple[str, ...],
    timeout: int,
) -> dict[str, Any]:
    probe = r'''
import json
import sys
import traceback
from pathlib import Path

from sd_core.tooling.harness import TranslationResult
from sd_core.translate.tracing import format_trace

path = Path(sys.argv[1])
module_name = sys.argv[2]
try:
    source = path.read_text(encoding="utf-8")
    result = TranslationResult.from_source(source, trace=True, name=module_name)
    trace = result.traces[0] if result.traces else None
    spans = getattr(trace, "spans", []) if trace is not None else []
    out = {
        "ok": True,
        "file": str(path),
        "module_name": module_name,
        "span_count": len(spans),
        "trace_text": format_trace(trace) if trace is not None else "(empty trace)",
    }
except Exception as exc:
    out = {
        "ok": False,
        "file": str(path),
        "module_name": module_name,
        "error": f"{type(exc).__name__}: {exc}",
        "trace_tail": traceback.format_exc()[-2000:],
    }
print(json.dumps(out, sort_keys=True))
'''
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=True) as f:
        f.write(probe)
        f.flush()
        cmd = [*runner, f.name, str(source_path.resolve()), module_name]
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=engine_worktree,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=_probe_env(engine_worktree),
                start_new_session=True,
            )
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
            return {
                "ok": False,
                "file": str(source_path),
                "module_name": module_name,
                "error": f"TimeoutExpired: translation trace exceeded {timeout}s",
                "trace_tail": ((stderr or "")[-2000:] if isinstance(stderr, str) else ""),
            }
    if proc.returncode != 0:
        return {
            "ok": False,
            "file": str(source_path),
            "module_name": module_name,
            "error": f"translation trace probe failed: exit={proc.returncode}",
            "trace_tail": stderr[-2000:],
        }
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    return {
        "ok": False,
        "file": str(source_path),
        "module_name": module_name,
        "error": "translation trace probe produced no JSON",
        "trace_tail": stderr[-2000:],
    }


def _safe_artifact_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "__" for ch in value)


class _TraceBuffer:
    def __init__(self, writer: _TraceWriter, file_name: str) -> None:
        self.writer = writer
        self.file_name = file_name
        self.records: dict[tuple[int, str, str], dict[str, Any]] = {}

    def add_slot(
        self,
        *,
        line: int,
        function: str,
        slot: str,
        candidates: list[dict[str, Any]],
        merged_annotation: str | None,
    ) -> None:
        fallback_reasons = sorted(
            {
                reason
                for candidate in candidates
                for reason in candidate.get("fallback_reasons", [])
                if reason
            }
        )
        if not merged_annotation and not fallback_reasons:
            fallback_reasons = ["missing element"]
        key = (line, function, slot)
        self.records[key] = {
            "file": self.file_name,
            "function": function,
            "line": line,
            "slot": slot,
            "raw_candidates": candidates,
            "rendered_annotation": merged_annotation,
            "merged_annotation": merged_annotation,
            "final_annotation": None,
            "insertion_happened": False,
            "insertion_reason": "not visited by annotator",
            "fallback_reason": "; ".join(fallback_reasons) if fallback_reasons else None,
        }

    def mark_insertion(
        self,
        *,
        line: int,
        function: str,
        slot: str,
        inserted: bool,
        reason: str,
        final_annotation: str | None,
    ) -> None:
        record = self.records.get((line, function, slot))
        if not record:
            return
        record["insertion_happened"] = inserted
        record["insertion_reason"] = reason
        record["final_annotation"] = final_annotation

    def flush(self) -> None:
        for key in sorted(self.records):
            self.writer.write(self.records[key])


def _function_types(
    analysis: dict[str, Any], trace: _TraceBuffer | None = None
) -> dict[tuple[int, str], dict[str, Any]]:
    out: dict[tuple[int, str], dict[str, Any]] = {}
    functions = analysis.get("functions", []) or []
    by_id = {f.get("fn_id"): f for f in functions}
    for fn in functions:
        pos = fn.get("source_position") or {}
        row = pos.get("row")
        name = fn.get("name")
        if not row or not name:
            continue
        param_candidates: dict[str, list[str]] = {}
        param_trace: dict[str, list[dict[str, Any]]] = {}
        returns: list[str] = []
        return_trace: list[dict[str, Any]] = []
        for inst_index, inst in enumerate(fn.get("instantiations", []) or []):
            for pname, events in (inst.get("params") or {}).items():
                typ, candidate = _events_type(events, by_id, instantiation=inst_index)
                param_trace.setdefault(pname, []).append(candidate)
                if typ:
                    param_candidates.setdefault(pname, []).append(typ)
            ret = inst.get("ret") or {}
            typ, reason = _render_element(ret.get("element"), by_id)
            return_trace.append(
                {
                    "instantiation": inst_index,
                    "raw_event": ret,
                    "raw_element": ret.get("element"),
                    "rendered_annotation": typ,
                    "fallback_reasons": [reason] if reason else [],
                    "top_origin_positions": _top_origin_positions([ret]),
                }
            )
            if typ:
                returns.append(typ)
        params = {
            pname: typ
            for pname, candidates in param_candidates.items()
            if (typ := _merge_types(candidates))
        }
        ret_type = _merge_types(returns)
        if trace:
            line = int(row)
            for pname, candidates in param_trace.items():
                trace.add_slot(
                    line=line,
                    function=str(name),
                    slot=f"param:{pname}",
                    candidates=candidates,
                    merged_annotation=params.get(pname),
                )
            if return_trace:
                trace.add_slot(
                    line=line,
                    function=str(name),
                    slot="return",
                    candidates=return_trace,
                    merged_annotation=ret_type,
                )
        out[(int(row), str(name))] = {"params": params, "return": ret_type}
    return out


def _events_type(
    events: Any, by_id: dict[Any, dict[str, Any]], *, instantiation: int | None = None
) -> tuple[Optional[str], dict[str, Any]]:
    if not events:
        return (
            None,
            {
                "instantiation": instantiation,
                "raw_events": [],
                "raw_elements": [],
                "rendered_events": [],
                "rendered_annotation": None,
                "fallback_reasons": ["missing events"],
                "top_origin_positions": [],
            },
        )
    if isinstance(events, dict):
        events = [events]
    rendered_events: list[str] = []
    raw_elements: list[Any] = []
    reasons: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            reasons.append("unknown event")
            continue
        raw_elements.append(event.get("element"))
        typ, reason = _render_element(event.get("element"), by_id)
        if typ:
            rendered_events.append(typ)
        if reason:
            reasons.append(reason)
    typ = _merge_types(rendered_events)
    return (
        typ,
        {
            "instantiation": instantiation,
            "raw_events": events,
            "raw_elements": raw_elements,
            "rendered_events": rendered_events,
            "rendered_annotation": typ,
            "fallback_reasons": reasons,
            "top_origin_positions": _top_origin_positions(events),
        },
    )


def _top_origin_positions(events: list[Any]) -> list[dict[str, Any]]:
    positions = []
    for event in events:
        if not isinstance(event, dict):
            continue
        element = event.get("element")
        position = event.get("source_position")
        if (
            isinstance(element, dict)
            and element.get("kind") == "top"
            and isinstance(position, dict)
        ):
            positions.append(position)
    return positions


def _merge_types(types: list[str]) -> Optional[str]:
    unique = sorted({t for t in types if t})
    if not unique:
        return None
    if len(unique) == 1:
        return unique[0]
    return f"Union[{', '.join(unique)}]"


def _element_type(elt: Any, by_id: dict[Any, dict[str, Any]]) -> Optional[str]:
    return _render_element(elt, by_id)[0]


def _render_element(elt: Any, by_id: dict[Any, dict[str, Any]]) -> tuple[Optional[str], str | None]:
    if not isinstance(elt, dict):
        return None, "missing element"
    kind = elt.get("kind")
    if kind == "pytype":
        name = elt.get("name")
        typ = _clean_type_name(str(name or "Any"))
        if typ == "ellipsis":
            return "Any", "ellipsis pytype"
        return typ, None if name else "missing pytype name"
    if kind in {"top", "bottom"}:
        return "Any", str(kind)
    if kind == "none":
        return "None", None
    if kind == "list":
        inner, reason = _render_element(elt.get("element"), by_id)
        return f"list[{inner or 'Any'}]", _nested_reason("list.element", reason, inner)
    if kind == "set":
        inner, reason = _render_element(elt.get("element"), by_id)
        return f"set[{inner or 'Any'}]", _nested_reason("set.element", reason, inner)
    if kind == "tuple":
        slots = elt.get("slots") or []
        if slots:
            rendered = [_render_element(s, by_id) for s in slots]
            inner = ", ".join(t or "Any" for t, _ in rendered)
            reason = _join_reasons(
                _nested_reason(f"tuple.slot[{i}]", reason, typ)
                for i, (typ, reason) in enumerate(rendered)
            )
            return f"tuple[{inner}]", reason
        inner, reason = _render_element(elt.get("element"), by_id)
        return f"tuple[{inner or 'Any'}, ...]", _nested_reason("tuple.element", reason, inner)
    if kind == "dict":
        key, key_reason = _render_element(elt.get("key"), by_id)
        val, val_reason = _render_element(elt.get("value"), by_id)
        return f"dict[{key or 'Any'}, {val or 'Any'}]", _join_reasons(
            [
                _nested_reason("dict.key", key_reason, key),
                _nested_reason("dict.value", val_reason, val),
            ]
        )
    if kind == "generator":
        inner, reason = _render_element(elt.get("element"), by_id)
        return f"Generator[{inner or 'Any'}, None, None]", _nested_reason(
            "generator.element", reason, inner
        )
    if kind == "union":
        rendered = [_render_element(e, by_id) for e in elt.get("elements", [])]
        return _merge_types([t for t, _ in rendered if t]), _join_reasons(
            _nested_reason(f"union.element[{i}]", reason, typ)
            for i, (typ, reason) in enumerate(rendered)
        )
    if kind == "instance":
        cls = elt.get("cls") or {}
        body = cls.get("body")
        fn = by_id.get(body)
        if fn and fn.get("name"):
            return str(fn["name"]), None
        return None, "missing instance class body"
    if kind == "class":
        return "type", None
    if kind == "callable":
        return "object", "callable->object"
    return None, f"unknown kind: {kind}"


def _nested_reason(prefix: str, reason: str | None, rendered: str | None) -> str | None:
    if reason:
        return f"{prefix}: {reason}"
    if rendered is None:
        return f"{prefix}: missing element"
    return None


def _join_reasons(reasons: Any) -> str | None:
    values = [reason for reason in reasons if reason]
    return "; ".join(values) if values else None


def _clean_type_name(name: str) -> str:
    if name in _NONE_TYPE_NAMES:
        return "None"
    if name.startswith("builtins."):
        return name.removeprefix("builtins.")
    return name


class _Annotator(ast.NodeTransformer):
    def __init__(
        self,
        function_types: dict[tuple[int, str], dict[str, Any]],
        variable_types: dict[tuple[int, str], str] | None = None,
        annotation_aliases: dict[str, str] | None = None,
        trace: _TraceBuffer | None = None,
    ) -> None:
        self.function_types = function_types
        self.variable_types = variable_types or {}
        self.annotation_aliases = annotation_aliases or {}
        self.stats = {
            "functions": 0,
            "params": 0,
            "returns": 0,
            "variables": 0,
        }
        self.needs_typing = False
        self.typing_imports: set[str] = set()
        self.trace = trace

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        self.generic_visit(node)
        self._annotate_function(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        self.generic_visit(node)
        self._annotate_function(node)
        return node

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        self.generic_visit(node)
        if len(node.targets) != 1:
            return node
        target = node.targets[0]
        name = _annotation_target_name(target)
        if name is None:
            return node
        annotation = self.variable_types.get((node.lineno, name))
        if annotation is None:
            return node
        annotation = _localize_annotation(
            annotation, self.annotation_aliases
        )
        rendered = _parse_annotation(annotation)
        self.stats["variables"] += 1
        imports = _typing_import_names({"variable": annotation})
        self.needs_typing = self.needs_typing or bool(imports)
        self.typing_imports.update(imports)
        return ast.copy_location(
            ast.AnnAssign(
                target=target,
                annotation=rendered,
                value=node.value,
                simple=int(isinstance(target, ast.Name)),
            ),
            node,
        )

    def _annotate_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        info = self.function_types.get((node.lineno, node.name))
        if not info:
            for arg in [
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
                *([node.args.vararg] if node.args.vararg else []),
                *([node.args.kwarg] if node.args.kwarg else []),
            ]:
                self._record_missing_slot(
                    node,
                    f"param:{arg.arg}",
                    "function absent from engine projection",
                )
            self._record_missing_slot(
                node,
                "return",
                "function absent from engine projection",
            )
            return
        changed = False
        params = info.get("params") or {}
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            if arg.arg not in params:
                self._record_missing_slot(
                    node,
                    f"param:{arg.arg}",
                    "no inferred parameter candidate",
                )
                continue
            slot = f"param:{arg.arg}"
            if arg.annotation is None:
                localized = _localize_annotation(
                    params[arg.arg], self.annotation_aliases
                )
                arg.annotation = _parse_annotation(localized)
                self.stats["params"] += 1
                changed = True
                self._mark_trace(node, slot, True, "inserted", localized)
            else:
                self._mark_trace(
                    node, slot, False, "existing annotation preserved", ast.unparse(arg.annotation)
                )
        for arg in (node.args.vararg, node.args.kwarg):
            if not arg or arg.arg not in params:
                if arg:
                    self._record_missing_slot(
                        node,
                        f"param:{arg.arg}",
                        "no inferred parameter candidate",
                    )
                continue
            slot = f"param:{arg.arg}"
            if arg.annotation is None:
                localized = _localize_annotation(
                    params[arg.arg], self.annotation_aliases
                )
                arg.annotation = _parse_annotation(localized)
                self.stats["params"] += 1
                changed = True
                self._mark_trace(node, slot, True, "inserted", localized)
            else:
                self._mark_trace(
                    node, slot, False, "existing annotation preserved", ast.unparse(arg.annotation)
                )
        ret = info.get("return")
        if ret and node.returns is None:
            localized = _localize_annotation(ret, self.annotation_aliases)
            node.returns = _parse_annotation(localized)
            self.stats["returns"] += 1
            changed = True
            self._mark_trace(node, "return", True, "inserted", localized)
        elif ret and node.returns is not None:
            self._mark_trace(
                node, "return", False, "existing annotation preserved", ast.unparse(node.returns)
            )
        elif not ret:
            self._record_missing_slot(node, "return", "no inferred return candidate")
        for pname in set(params) - {
            arg.arg
            for arg in [
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
                *([node.args.vararg] if node.args.vararg else []),
                *([node.args.kwarg] if node.args.kwarg else []),
            ]
        }:
            self._mark_trace(node, f"param:{pname}", False, "parameter not present in AST", None)
        if changed:
            self.stats["functions"] += 1
            imports = _typing_import_names(info)
            self.needs_typing = self.needs_typing or bool(imports)
            self.typing_imports.update(imports)

    def _mark_trace(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        slot: str,
        inserted: bool,
        reason: str,
        final_annotation: str | None,
    ) -> None:
        if self.trace:
            self.trace.mark_insertion(
                line=node.lineno,
                function=node.name,
                slot=slot,
                inserted=inserted,
                reason=reason,
                final_annotation=final_annotation,
            )

    def _record_missing_slot(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        slot: str,
        reason: str,
    ) -> None:
        if not self.trace:
            return
        self.trace.add_slot(
            line=node.lineno,
            function=node.name,
            slot=slot,
            candidates=[{
                "instantiation": None,
                "raw_events": [],
                "raw_elements": [],
                "rendered_events": [],
                "rendered_annotation": None,
                "fallback_reasons": [reason],
                "top_origin_positions": [],
            }],
            merged_annotation=None,
        )
        self._mark_trace(node, slot, False, reason, None)


def _needs_typing_import(info: dict[str, Any]) -> bool:
    return bool(_typing_import_names(info))


def _typing_import_names(info: dict[str, Any]) -> set[str]:
    values = list((info.get("params") or {}).values())
    if info.get("return"):
        values.append(info["return"])
    if info.get("variable"):
        values.append(info["variable"])
    imports: set[str] = set()
    for value in values:
        if "Any" in value or "Union[" in value:
            imports.update({"Any", "Union"})
        if "Generator" in value:
            imports.add("Generator")
    return imports


def _parse_annotation(value: str) -> ast.expr:
    return ast.parse(value, mode="eval").body


def _annotation_aliases(tree: ast.Module) -> dict[str, str]:
    """Map canonical analysis names to spellings already valid in a file."""

    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for imported in node.names:
                if imported.name == "*":
                    continue
                aliases[f"{node.module}.{imported.name}"] = (
                    imported.asname or imported.name
                )
        elif isinstance(node, ast.Import):
            for imported in node.names:
                if imported.asname:
                    aliases[imported.name] = imported.asname
    return aliases


def _localize_annotation(value: str, aliases: dict[str, str]) -> str:
    """Render canonical fact names through the source file's import surface."""

    for canonical, local in sorted(
        aliases.items(), key=lambda item: len(item[0]), reverse=True
    ):
        value = re.sub(
            rf"(?<![\w.]){re.escape(canonical)}(?!\w)",
            local,
            value,
        )
    return value


def _annotate_source(
    source: str,
    function_types: dict[tuple[int, str], dict[str, Any]],
    variable_types: dict[tuple[int, str], str] | None = None,
    trace: _TraceBuffer | None = None,
) -> tuple[str, dict[str, int]]:
    tree = ast.parse(source)
    annotator = _Annotator(
        function_types,
        variable_types=variable_types,
        annotation_aliases=_annotation_aliases(tree),
        trace=trace,
    )
    tree = annotator.visit(tree)
    ast.fix_missing_locations(tree)
    if annotator.needs_typing:
        _ensure_typing_import(tree, annotator.typing_imports)
    if trace:
        trace.flush()
    return ast.unparse(tree) + "\n", annotator.stats


def _annotation_target_name(target: ast.expr) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _ensure_typing_import(tree: ast.AST, names: set[str]) -> None:
    assert isinstance(tree, ast.Module)
    ordered_names = [name for name in ("Any", "Generator", "Union") if name in names]
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "typing":
            existing = {alias.name for alias in node.names}
            for name in ordered_names:
                if name not in existing:
                    node.names.append(ast.alias(name=name))
            return
    insert_at = 0
    if tree.body and isinstance(tree.body[0], ast.Expr):
        insert_at = 1
    while (
        insert_at < len(tree.body)
        and isinstance(tree.body[insert_at], ast.ImportFrom)
        and tree.body[insert_at].module == "__future__"
    ):
        insert_at += 1
    tree.body.insert(
        insert_at,
        ast.ImportFrom(
            module="typing",
            names=[ast.alias(name=name) for name in ordered_names],
            level=0,
        ),
    )
