"""Emit TypyBench annotated-source predictions from a pinned Archway engine.

This is intentionally a narrow bridge: TypyBench scores source trees, while the
existing benchmark adapters mostly score location maps. The functions here run
the pinned engine read-only in a subprocess, collect function/parameter/return
types from the finalized analysis projection, and write syntactically valid
Python predictions under ``predictions/<repo>/``.
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


_NONE_TYPE_NAMES = {"builtins.NoneType", "NoneType"}
_TRACE_ENV_VAR = "ARCHWAY_TYPYBENCH_TRACE_JSONL"


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
) -> EmitStats:
    """Analyze one TypyBench repo and write ``predictions/<repo_name>``.

    Files that the engine cannot analyze are still copied, unannotated. That is
    the honest TypyBench contract: unsupported locations remain missing instead
    of being fabricated.
    """

    untyped_root = Path(untyped_root)
    dest_root = Path(predictions_root) / repo_name
    if overwrite and dest_root.exists():
        shutil.rmtree(dest_root)
    if not dest_root.exists():
        dest_root.mkdir(parents=True)

    files = sorted(p for p in untyped_root.rglob("*.py") if p.is_file())
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
    failures: list[dict[str, str]] = []
    file_profiles: list[FileProfile] = []

    try:
        started = time.monotonic()
        for src in files:
            file_started = time.monotonic()
            rel = src.relative_to(untyped_root)
            rel_s = str(rel)
            dest = dest_root / rel
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

            probe_started = time.monotonic()
            record = _run_engine_probe_file(
                engine_worktree=Path(engine_worktree),
                source_path=src,
                module_name=src.stem,
                runner=runner,
                timeout=max(1, min(per_file_timeout, int(remaining))),
                body_summary_consumption=body_summary_consumption,
                analysis_product=analysis_product,
                analysis_observation_mode=analysis_observation_mode,
                type_requirements_assume_closed=type_requirements_assume_closed,
            )
            seconds_probe = time.monotonic() - probe_started
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

            files_analyzed += 1
            file_trace = trace.for_file(rel_s) if trace else None
            render_started = time.monotonic()
            function_types = _function_types(record.get("analysis", {}), trace=file_trace)
            seconds_render = time.monotonic() - render_started
            functions_seen += len(function_types)
            raw = src.read_text(encoding="utf-8")
            annotate_started = time.monotonic()
            try:
                annotated, file_stats = _annotate_source(raw, function_types, trace=file_trace)
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
        failures=tuple(failures),
        file_profiles=tuple(file_profiles),
        engine_sha=engine_sha,
    )


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
        cmd = [*runner, f.name, str(source_path.resolve()), module_name]
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
        trace: _TraceBuffer | None = None,
    ) -> None:
        self.function_types = function_types
        self.stats = {"functions": 0, "params": 0, "returns": 0}
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

    def _annotate_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        info = self.function_types.get((node.lineno, node.name))
        if not info:
            return
        changed = False
        params = info.get("params") or {}
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            if arg.arg not in params:
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


def _needs_typing_import(info: dict[str, Any]) -> bool:
    return bool(_typing_import_names(info))


def _typing_import_names(info: dict[str, Any]) -> set[str]:
    values = list((info.get("params") or {}).values())
    if info.get("return"):
        values.append(info["return"])
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
    trace: _TraceBuffer | None = None,
) -> tuple[str, dict[str, int]]:
    tree = ast.parse(source)
    annotator = _Annotator(function_types, trace=trace)
    tree = annotator.visit(tree)
    ast.fix_missing_locations(tree)
    if annotator.needs_typing:
        _ensure_typing_import(tree, annotator.typing_imports)
    if trace:
        trace.flush()
    return ast.unparse(tree) + "\n", annotator.stats


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
