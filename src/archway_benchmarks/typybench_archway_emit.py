"""Emit TypyBench predictions from one persistent successor analysis session.

TypyBench scores annotated source trees.  Archway analysis remains diagram-only;
the AST is used here solely as a post-analysis output adapter that inserts facts
already produced by the successor runtime into a copy of the source tree.
"""
from __future__ import annotations

import ast
import json
import os
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
            except ValueError:
                continue
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
    failures: tuple[dict[str, str], ...] = field(default_factory=tuple)
    file_profiles: tuple[FileProfile, ...] = field(default_factory=tuple)
    engine_sha: str | None = None


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
    body_summary_consumption: str = "off",
    analysis_product: str = "standalone",
    analysis_observation_mode: str = "summary",
    type_requirements_assume_closed: bool = False,
    checkpoint_roots: bool = True,
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
            checkpoint_roots=checkpoint_roots,
            diagnostic_details=False,
        )
        seconds_repo_probe = time.monotonic() - probe_started
        for src in files:
            file_started = time.monotonic()
            rel = src.relative_to(untyped_root)
            rel_s = str(rel)
            dest = dest_root / rel
            record = repo_record
            seconds_probe = seconds_repo_probe
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
        failures=tuple(failures),
        file_profiles=tuple(file_profiles),
        engine_sha=engine_sha,
    )


def _successor_function_types(
    observations: list[dict[str, Any]], trace: _TraceBuffer | None = None
) -> dict[tuple[int, str], dict[str, Any]]:
    """Render compact successor observations into the annotation adapter shape."""

    candidates: dict[tuple[int, str], dict[str, list[str]]] = {}
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
        candidates.setdefault((int(line), function), {}).setdefault(
            slot, []
        ).extend(values)

    rendered: dict[tuple[int, str], dict[str, Any]] = {}
    for key, slots in candidates.items():
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
            item.get("function") is not None or "." not in str(name)
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


def _run_successor_repo_probe(
    *,
    engine_worktree: Path,
    source_root: Path,
    runner: tuple[str, ...],
    timeout: int,
    demand_limit: int | None = None,
    checkpoint_roots: bool = False,
    checkpoint_size: int = 8,
    checkpoint_tail_start: int | None = None,
    checkpoint_tail_count: int | None = None,
    body_label: str | None = None,
    body_timeout: int | None = None,
    callable_input_exact_limit: int | None = None,
    sample_rate_hz: float | None = None,
    sample_body_label: str | None = None,
    record_timings: bool = False,
    diagnostic_details: bool = True,
    collect_predictions: bool = True,
) -> dict[str, Any]:
    """Run one successor session for the complete repository source graph."""

    if (
        body_timeout is not None
        and body_label is None
        and sample_body_label is None
    ):
        raise ValueError(
            "body_timeout requires body_label or sample_body_label"
        )
    if callable_input_exact_limit is not None and callable_input_exact_limit < 0:
        raise ValueError("callable_input_exact_limit must be non-negative")
    if checkpoint_size <= 0:
        raise ValueError("checkpoint_size must be positive")
    if checkpoint_tail_start is not None and checkpoint_tail_start < 0:
        raise ValueError("checkpoint_tail_start must be non-negative")
    if checkpoint_tail_count is not None and checkpoint_tail_count <= 0:
        raise ValueError("checkpoint_tail_count must be positive")
    if sample_rate_hz is not None and sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    if sample_body_label is not None and sample_rate_hz is None:
        raise ValueError("sample_body_label requires sample_rate_hz")

    engine_worktree = Path(engine_worktree).resolve()
    probe = r'''
import json
import os
import signal
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

from sd_core.analysis.diagram_analysis import open_hybrid_program_session
from sd_core.tooling.harness import TranslationResult

root = Path(sys.argv[1])
demand_limit = int(sys.argv[2]) or None
checkpoint_roots = sys.argv[3] == "checkpoint"
requested_body_label = sys.argv[4] or None
requested_body_timeout = int(sys.argv[5]) or None
exact_limit_arg = int(sys.argv[6])
callable_input_exact_limit = exact_limit_arg if exact_limit_arg >= 0 else None
sample_rate_hz = float(sys.argv[7]) or None
sample_body_label = sys.argv[8] or None
record_timings = sys.argv[9] == "timings"
diagnostic_details = sys.argv[10] == "diagnostics"
collect_predictions = sys.argv[11] == "predictions"
checkpoint_size = int(sys.argv[12])
checkpoint_tail_start = int(sys.argv[13])
checkpoint_tail_count = int(sys.argv[14])

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
    source_root = max(
        (
            candidate for candidate in source_roots
            if path.is_relative_to(candidate)
        ),
        key=lambda candidate: len(candidate.parts),
    )
    rel = path.relative_to(source_root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or "__init__"

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
    session = open_hybrid_program_session(
        modules, entry, record_events=False,
        record_timings=record_timings,
        body_observations_only=True,
        class_field_observations=True,
        callable_input_exact_limit=callable_input_exact_limit,
        contextual_summary_evaluation=True,
    )
    session_open_seconds = time.monotonic() - phase_started
    print(f"ARCHWAY_PHASE session_open {session_open_seconds:.6f}", file=sys.stderr, flush=True)
    # Seed the selected program entry in the persistent scheduler.  Every
    # module is translated and available for later demands, but treating every
    # library module as an eager entry point creates a monolithic execution
    # wave.  The observation workload below extends this same fact store and
    # topology with only the additional module/body roots it actually needs.
    forward = session.run_forward()
    forward_seconds = time.monotonic() - phase_started
    print(f"ARCHWAY_PHASE forward {forward_seconds:.6f}", file=sys.stderr, flush=True)
    observations = session.type_observations()
    missing_observations = sorted((
        item for item in observations
        if item.kind in {"parameter", "return", "variable"}
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
    all_signature_roots = session.observation_workload_roots(missing)
    print(f"ARCHWAY_PHASE signature_demands {len(missing)}", file=sys.stderr, flush=True)
    requested = (
        missing
        if requested_body_label
        else missing[:demand_limit] if demand_limit is not None else missing
    )
    signature_roots = session.observation_workload_roots(requested)
    body_labels = {
        template.body_morphism_id: (
            f"{template.module.dotted if template.module else '?'}:"
            f"{template.function or template.name}"
        )
        for plan in session.module_plans.values()
        for template in plan.templates
    }
    if requested_body_label:
        signature_roots = tuple(
            root_address for root_address in signature_roots
            if body_labels.get(
                getattr(root_address.subject, "body_morphism_id", "")
            ) == requested_body_label
        )
    print(f"ARCHWAY_PHASE body_roots {len(signature_roots)}", file=sys.stderr, flush=True)
    if diagnostic_details and len(signature_roots) <= 32:
        print(
            "ARCHWAY_ROOTS " + json.dumps([
                body_labels.get(
                    getattr(item.subject, "body_morphism_id", ""), "?"
                )
                for item in signature_roots
            ]),
            file=sys.stderr,
            flush=True,
        )
    sampling_profile = None
    targeted_profiler = None
    if sample_rate_hz and sample_body_label is None and signature_roots:
        from sd_core.tooling.sampling_profile import SamplingProfiler
        targeted_profiler = SamplingProfiler(
            rate_hz=sample_rate_hz,
            project_marker="/sd_core/",
        )
        targeted_profiler.__enter__()
    timed_out_body = False
    timeout_signal = signal.SIGALRM
    if requested_body_timeout:
        def timeout_body(_signum, _frame):
            raise TimeoutError("diagnostic body cutoff")
        signal.signal(timeout_signal, timeout_body)
    if checkpoint_roots:
        targeted = None
        body_profiles = []
        # Compact corpus runs admit a small batch at a time into the same
        # persistent session.  This preserves shared knowledge and affected-
        # region convergence while avoiding both one scheduler drain per body
        # and the enormous topology wave produced by collective admission.
        # Admit bounded cohorts into the same persistent scheduler. One root
        # per drain repeats global stability checks and convergence work for
        # every signature body; admitting the entire repository at once can
        # create an unnecessarily large unstable topology wave. Eight roots
        # preserves frequent durable progress while allowing related demands
        # to share discovery and SCC convergence.
        prefix_end = min(checkpoint_tail_start, len(signature_roots))
        prefix = tuple(
            signature_roots[index:index + checkpoint_size]
            for index in range(0, prefix_end, checkpoint_size)
        ) if checkpoint_tail_start >= 0 else ()
        tail_start = prefix_end if checkpoint_tail_start >= 0 else 0
        tail_size = 1 if checkpoint_tail_start >= 0 else checkpoint_size
        tail_end = (
            min(len(signature_roots), tail_start + checkpoint_tail_count)
            if checkpoint_tail_count > 0 else len(signature_roots)
        )
        root_batches = prefix + tuple(
            signature_roots[index:index + tail_size]
            for index in range(tail_start, tail_end, tail_size)
        )
        print(
            "ARCHWAY_BODY_PLAN " + json.dumps([[
                body_labels.get(
                    getattr(root.subject, "body_morphism_id", ""), "?"
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
            summary_registry = session.invocation_registry.callable_summaries
            applications_before = frozenset(
                summary_registry.applications
            ) if diagnostic_details and summary_registry is not None else frozenset()
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
            body_id = getattr(root_address.subject, "body_morphism_id", "")
            body_label = body_labels.get(body_id, "?")
            sample_this_body = (
                sample_rate_hz and body_label == sample_body_label
            )
            cutoff_this_body = (
                requested_body_timeout
                and body_label in {sample_body_label, requested_body_label}
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
                targeted = session.observe(root_batch)
            except TimeoutError:
                timed_out_body = True
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
                "top_execution_families": sorted(
                    family_deltas.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:8],
                "top_family_seconds": sorted(
                    family_second_deltas.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:8],
                "top_new_application_callers": (
                    Counter(
                        (
                            spec.invocation.caller_context,
                            spec.callable_value.body_morphism_id,
                        )
                        for application, spec
                        in summary_registry.applications.items()
                        if application not in applications_before
                    ).most_common(12)
                    if diagnostic_details and summary_registry is not None
                    else []
                ),
                "root_id": root_address.id,
                "root_ids": [item.id for item in root_batch],
                "root_labels": [
                    body_labels.get(
                        getattr(item.subject, "body_morphism_id", ""), "?"
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
            # One compact line per eight-root cohort is intentionally retained
            # in production-light runs. It is negligible beside convergence
            # work and survives a bounded subprocess timeout, unlike the final
            # JSON summary, so large-repository replay growth remains
            # diagnosable without enabling detailed tracing.
            print(
                f"ARCHWAY_BODY {index}/{len(root_batches)} "
                f"{body_profile['seconds']:.6f} "
                f"exec={body_profile['executions']} "
                f"topology={body_profile['topology_changes']} "
                f"{body_profile['label']}"
                + (f" {root_address.id}" if diagnostic_details else ""),
                file=sys.stderr, flush=True,
            )
            if timed_out_body:
                break
    else:
        body_profiles = []
        # SamplingProfiler owns ITIMER_VIRTUAL/SIGVTALRM.  Keep the bounded
        # body cutoff on the independent wall-clock alarm so both diagnostics
        # remain active when profiling one long-running body.
        if requested_body_timeout and signature_roots:
            signal.alarm(requested_body_timeout)
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
    observation_projection_seconds = time.monotonic() - projection_started
    scheduler_telemetry = (
        dict(session.scheduler.aggregate_production_telemetry)
        if diagnostic_details else {
            "unique_production_count": (
                session.scheduler.unique_production_count
            ),
            "production_execution_count": (
                session.scheduler.production_execution_count
            ),
            "repeated_production_count": (
                session.scheduler.repeated_production_count
            ),
            "component_recompute_count": (
                session.scheduler.graph.component_recompute_count
            ),
            "component_recompute_seconds": (
                session.scheduler.graph.component_recompute_seconds
            ),
            "component_node_visits": (
                session.scheduler.graph.component_node_visits
            ),
            "component_edge_visits": (
                session.scheduler.graph.component_edge_visits
            ),
            "component_incremental_refresh_count": (
                session.scheduler.graph.component_incremental_refresh_count
            ),
            "component_edge_update_telemetry": dict(
                session.scheduler.graph.component_edge_update_telemetry
            ),
        }
    )
    summary_registry = (
        session.invocation_registry.callable_summaries
        if session.invocation_registry is not None else None
    )
    unresolved_summary_bodies = Counter()
    if diagnostic_details and collect_predictions and summary_registry is not None:
        callable_labels = {
            body_id: f"{boundary.module_name}:{boundary.qualified_name}"
            for body_id, boundary
            in session.callable_boundaries_by_body.items()
        }
        for application_address, spec in summary_registry.applications.items():
            if session.store.resolved(application_address) is not None:
                continue
            unresolved_summary_bodies[
                body_labels.get(
                    spec.callable_value.body_morphism_id,
                    callable_labels.get(
                        spec.callable_value.body_morphism_id,
                        spec.callable_value.body_morphism_id,
                    ),
                )
            ] += 1
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
            "signature_body_roots": len(all_signature_roots),
            "body_profiles": body_profiles,
            "timed_out_body": timed_out_body,
            "forward_events": len(forward.events),
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
            "production_replay_hotspots": (
                session.scheduler.production_replay_hotspots()
                if diagnostic_details else ()
            ),
            "morphism_transfer_reuse": dict(
                session.morphism_transfer_reuse_counts()
            ) if diagnostic_details else {},
            "morphism_transfer_reuse_by_operation": dict(
                session.morphism_transfer_reuse_by_operation()
            ) if diagnostic_details else {},
            "atomic_effect_gaps": dict(
                session.atomic_effect_gap_counts()
            ) if diagnostic_details else {},
            "morphism_fact_output_barriers": dict(
                session.morphism_fact_output_barriers()
            ) if diagnostic_details else {},
            "morphism_read_intersections": dict(
                session.morphism_read_intersections()
            ) if diagnostic_details else {},
            "invocation_contexts": dict(
                session.invocation_context_counts()
            ) if diagnostic_details else {},
            "invocation_inputs": dict(
                session.invocation_input_growth_counts()
            ) if diagnostic_details else {},
            "invocation_admissions": dict(
                session.invocation_admission_counts()
            ) if diagnostic_details else {},
            "sampling_profile": sampling_profile,
            "unresolved_summary_bodies": dict(
                unresolved_summary_bodies.most_common(32)
            ),
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
    out = {
        "ok": False,
        "error": f"{type(exc).__name__}: {exc}",
        "trace_tail": traceback.format_exc()[-2400:],
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
            body_label or "",
            str(body_timeout or 0),
            str(
                callable_input_exact_limit
                if callable_input_exact_limit is not None else -1
            ),
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
        ]
        try:
            proc = subprocess.Popen(
                cmd, cwd=engine_worktree, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
                env=_probe_env(engine_worktree), start_new_session=True,
            )
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            _stdout, stderr = proc.communicate()
            return {
                "ok": False,
                "error": f"TimeoutExpired: analysis exceeded {timeout}s",
                "trace_tail": stderr[-2400:],
                "analysis_summary": _probe_progress(stderr),
            }
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": f"engine probe failed: exit={proc.returncode}",
            "trace_tail": stderr[-2400:],
            "analysis_summary": _probe_progress(stderr),
        }
    for line in reversed(stdout.splitlines()):
        if line.strip().startswith("{"):
            return json.loads(line)
    return {"ok": False, "error": "engine probe produced no JSON", "trace_tail": stderr[-2400:]}


def _run_engine_probe(
    *,
    engine_worktree: Path,
    source_root: Path,
    runner: tuple[str, ...],
    timeout: int,
    per_file_timeout: int = 60,
    body_summary_consumption: str | None = None,
    analysis_product: str = "standalone",
    analysis_observation_mode: str = "summary",
    type_requirements_assume_closed: bool = False,
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
            body_summary_consumption=body_summary_consumption,
            analysis_product=analysis_product,
            analysis_observation_mode=analysis_observation_mode,
            type_requirements_assume_closed=type_requirements_assume_closed,
        )
    return out


def _run_engine_probe_file(
    *,
    engine_worktree: Path,
    source_path: Path,
    module_name: str,
    runner: tuple[str, ...],
    timeout: int,
    body_summary_consumption: str | None = None,
    analysis_product: str = "standalone",
    analysis_observation_mode: str = "summary",
    type_requirements_assume_closed: bool = False,
) -> dict[str, Any]:
    probe = r'''
import json
import os
import sys
import traceback
from pathlib import Path

try:
    from sd_core.analysis_server import _encode_finalized, analyze_source
    from sd_core.runners.analysis_observability import AnalysisObservationConfig
    from sd_core.runners.file_results import FileAnalysisFailure, analyze_source_file_result
except Exception:  # pragma: no cover - compatibility with older engine pins
    AnalysisObservationConfig = None
    FileAnalysisFailure = None
    _encode_finalized = None
    analyze_source_file_result = None
    from sd_core.analysis_server import analyze_source

path = Path(sys.argv[1])
module_name = sys.argv[2]
try:
    source = path.read_text(encoding="utf-8")
    analysis_summary = None
    if (
        analyze_source_file_result is not None
        and AnalysisObservationConfig is not None
        and _encode_finalized is not None
    ):
        observation_mode = os.environ.get("ARCHWAY_ANALYSIS_OBSERVATION", "summary")
        if observation_mode == "diagnostic":
            observation_config = AnalysisObservationConfig.diagnostic()
        elif observation_mode == "off":
            observation_config = AnalysisObservationConfig.off()
        else:
            observation_config = AnalysisObservationConfig.summary()
        kwargs = {
            "module": module_name,
            "repo_path": str(path),
            "observation_config": observation_config,
        }
        body_summary_consumption = os.environ.get("ARCHWAY_BODY_SUMMARY_CONSUMPTION", "off")
        if body_summary_consumption != "off":
            kwargs["body_summary_consumption"] = body_summary_consumption
        analysis_product = os.environ.get("ARCHWAY_ANALYSIS_PRODUCT", "standalone")
        if analysis_product != "standalone":
            kwargs["analysis_product"] = analysis_product
        if os.environ.get("ARCHWAY_TYPE_REQUIREMENTS_ASSUME_CLOSED") in {
            "1", "true", "yes", "on",
        }:
            kwargs["type_requirements_assume_closed"] = True
        file_result = analyze_source_file_result(source, **kwargs)
        analysis_summary = file_result.to_jsonable().get("analysis_summary")
        if file_result.status != "analyzed" or file_result.run is None:
            if FileAnalysisFailure is not None:
                raise FileAnalysisFailure(file_result)
            raise RuntimeError(f"file analysis failed: {file_result.status}")
        analysis = _encode_finalized(file_result.run.finalized)
        analysis["module_name"] = module_name
        analysis["status"] = file_result.status
        analysis["file_result"] = file_result.to_jsonable()
    else:
        analysis = analyze_source(source, module_name)
    out = {
        "ok": True,
        "analysis": analysis,
        "analysis_summary": analysis_summary,
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
                    body_summary_consumption=body_summary_consumption,
                    analysis_product=analysis_product,
                    analysis_observation_mode=analysis_observation_mode,
                    type_requirements_assume_closed=type_requirements_assume_closed,
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
    body_summary_consumption: str | None = None,
    analysis_product: str = "standalone",
    analysis_observation_mode: str = "summary",
    type_requirements_assume_closed: bool = False,
) -> dict[str, str]:
    env = os.environ.copy()
    if body_summary_consumption:
        env["ARCHWAY_BODY_SUMMARY_CONSUMPTION"] = body_summary_consumption
    env["ARCHWAY_ANALYSIS_PRODUCT"] = analysis_product
    env["ARCHWAY_ANALYSIS_OBSERVATION"] = analysis_observation_mode
    if type_requirements_assume_closed:
        env["ARCHWAY_TYPE_REQUIREMENTS_ASSUME_CLOSED"] = "1"
    else:
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
    body_summary_consumption: str | None = None,
    analysis_product: str = "standalone",
    type_requirements_assume_closed: bool = False,
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
            body_summary_consumption=body_summary_consumption,
            analysis_product=analysis_product,
            type_requirements_assume_closed=type_requirements_assume_closed,
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
    body_summary_consumption: str | None = None,
    analysis_product: str = "standalone",
    type_requirements_assume_closed: bool = False,
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
            kwargs = {}
            body_summary_consumption = os.environ.get("ARCHWAY_BODY_SUMMARY_CONSUMPTION", "off")
            if body_summary_consumption != "off":
                kwargs["body_summary_consumption"] = body_summary_consumption
            analysis_product = os.environ.get("ARCHWAY_ANALYSIS_PRODUCT", "standalone")
            if analysis_product != "standalone":
                kwargs["analysis_product"] = analysis_product
            if os.environ.get("ARCHWAY_TYPE_REQUIREMENTS_ASSUME_CLOSED") in {
                "1", "true", "yes", "on",
            }:
                kwargs["type_requirements_assume_closed"] = True
            result = analyze_source(source, module_name, **kwargs)
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
                env=_probe_env(
                    engine_worktree,
                    body_summary_consumption=body_summary_consumption,
                    analysis_product=analysis_product,
                    type_requirements_assume_closed=type_requirements_assume_closed,
                ),
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
                    "raw_element": ret.get("element"),
                    "rendered_annotation": typ,
                    "fallback_reasons": [reason] if reason else [],
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
                "raw_elements": [],
                "rendered_events": [],
                "rendered_annotation": None,
                "fallback_reasons": ["missing events"],
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
            "raw_elements": raw_elements,
            "rendered_events": rendered_events,
            "rendered_annotation": typ,
            "fallback_reasons": reasons,
        },
    )


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
        trace: _TraceBuffer | None = None,
    ) -> None:
        self.function_types = function_types
        self.variable_types = variable_types or {}
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
                arg.annotation = _parse_annotation(params[arg.arg])
                self.stats["params"] += 1
                changed = True
                self._mark_trace(node, slot, True, "inserted", params[arg.arg])
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
                arg.annotation = _parse_annotation(params[arg.arg])
                self.stats["params"] += 1
                changed = True
                self._mark_trace(node, slot, True, "inserted", params[arg.arg])
            else:
                self._mark_trace(
                    node, slot, False, "existing annotation preserved", ast.unparse(arg.annotation)
                )
        ret = info.get("return")
        if ret and node.returns is None:
            node.returns = _parse_annotation(ret)
            self.stats["returns"] += 1
            changed = True
            self._mark_trace(node, "return", True, "inserted", ret)
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
                "raw_elements": [],
                "rendered_events": [],
                "rendered_annotation": None,
                "fallback_reasons": [reason],
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
