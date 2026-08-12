"""PyCG benchmark loader, scorer, and Archway runner.

This module targets PyCG's published benchmark shapes:

```
micro-benchmark/snippets/<category>/<case>/main.py
micro-benchmark/snippets/<category>/<case>/callgraph.json
data/macro-benchmark/projects/<project>/...
data/macro-benchmark/ground-truth-cgs/<project>.json
```

The scorer is intentionally graph-shaped rather than annotation-shaped. It
reports edge precision/recall/F1 with explicit case and edge denominators.
Archway predictions are produced from Archway call-relation surfaces when
available; structural name hints remain diagnostic and are not claim-grade
semantic call targets.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import multiprocessing
import queue
import resource
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Literal, Mapping

Edge = tuple[str, str]
EdgeProvider = Literal["successor", "coordinated", "legacy"]


class PyCGCaseExecutionError(RuntimeError):
    def __init__(self, message: str, evidence: dict[str, object]) -> None:
        super().__init__(message)
        self.analysis_evidence = evidence


class PyCGCaseTimeoutError(TimeoutError):
    def __init__(self, message: str, evidence: dict[str, object]) -> None:
        super().__init__(message)
        self.analysis_evidence = evidence


@dataclass(frozen=True)
class PyCGCase:
    suite: str
    suite_path: str
    root: Path
    package_root: Path
    main_path: Path
    source_paths: tuple[Path, ...]
    expected: dict[str, tuple[str, ...]]

    @property
    def expected_edges(self) -> frozenset[Edge]:
        return frozenset(expected_edges_from_callgraph(self.expected))

    @property
    def expected_edge_occurrence_count(self) -> int:
        return sum(len(callees) for callees in self.expected.values())


@dataclass(frozen=True)
class SuccessorEdgeResult:
    """Thin PyCG projection plus shared-session cost evidence."""

    edges: frozenset[Edge]
    root_demands: int
    cache_hits: int
    production_events: int
    knowledge_deltas: int
    topology_growth: int
    evidence: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class EdgeScore:
    true_positive: int
    false_positive: int
    false_negative: int
    recall_true_positive: int | None = None

    @property
    def precision(self) -> float:
        denom = self.true_positive + self.false_positive
        return self.true_positive / denom if denom else 0.0

    @property
    def recall(self) -> float:
        true_positive = (
            self.true_positive
            if self.recall_true_positive is None
            else self.recall_true_positive
        )
        denom = true_positive + self.false_negative
        return true_positive / denom if denom else 0.0

    @property
    def f1(self) -> float:
        denom = self.precision + self.recall
        return 2 * self.precision * self.recall / denom if denom else 0.0

    def to_jsonable(self) -> dict[str, float | int]:
        payload = {
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }
        if self.recall_true_positive is not None:
            payload["recall_true_positive"] = self.recall_true_positive
        return payload


@dataclass(frozen=True)
class PyCGCaseResult:
    suite_path: str
    expected_edge_count: int
    predicted_edge_count: int
    score: EdgeScore
    status: str = "ok"
    error: str | None = None
    elapsed_seconds: float = 0.0
    predicted_edges: tuple[Edge, ...] = ()
    missing_edges: tuple[Edge, ...] = ()
    extra_edges: tuple[Edge, ...] = ()
    analysis_evidence: dict[str, object] = field(default_factory=dict)

    def to_jsonable(self) -> dict:
        return {
            "suite_path": self.suite_path,
            "expected_edge_count": self.expected_edge_count,
            "predicted_edge_count": self.predicted_edge_count,
            "score": self.score.to_jsonable(),
            "status": self.status,
            "error": self.error,
            "elapsed_seconds": self.elapsed_seconds,
            "predicted_edges": [list(edge) for edge in self.predicted_edges],
            "missing_edges": [list(edge) for edge in self.missing_edges],
            "extra_edges": [list(edge) for edge in self.extra_edges],
            "analysis_evidence": self.analysis_evidence,
        }


@dataclass(frozen=True)
class PyCGRunResult:
    suite: str
    corpus_root: str
    engine_root: str
    edge_provider: EdgeProvider
    cases_total: int
    cases_attempted: int
    cases_ok: int
    cases_error: int
    expected_edges_total: int
    predicted_edges_total: int
    score: EdgeScore
    elapsed_seconds: float
    cases: tuple[PyCGCaseResult, ...] = field(default_factory=tuple)
    project_scores: dict[str, dict[str, float | int]] = field(default_factory=dict)

    def to_jsonable(self) -> dict:
        return {
            "suite": self.suite,
            "corpus_root": self.corpus_root,
            "engine_root": self.engine_root,
            "edge_provider": self.edge_provider,
            "cases_total": self.cases_total,
            "cases_attempted": self.cases_attempted,
            "cases_ok": self.cases_ok,
            "cases_error": self.cases_error,
            "expected_edges_total": self.expected_edges_total,
            "predicted_edges_total": self.predicted_edges_total,
            "score": self.score.to_jsonable(),
            "elapsed_seconds": self.elapsed_seconds,
            "project_scores": self.project_scores,
            "cases": [case.to_jsonable() for case in self.cases],
        }


def expected_edges_from_callgraph(callgraph: Mapping[str, Iterable[str]]) -> set[Edge]:
    return {
        (str(caller), str(callee))
        for caller, callees in callgraph.items()
        for callee in callees
    }


def score_edges(expected: set[Edge], predicted: set[Edge]) -> EdgeScore:
    return EdgeScore(
        true_positive=len(expected & predicted),
        false_positive=len(predicted - expected),
        false_negative=len(expected - predicted),
    )


def score_adjacency_lists(
    expected: Mapping[str, Iterable[str]],
    predicted_edges: set[Edge],
) -> EdgeScore:
    """Score like PyCG's macro comparison script.

    Precision iterates predicted adjacency-list entries and checks membership in
    expected[caller]. Recall iterates expected adjacency-list entries and checks
    membership in actual[caller]. That preserves the official denominator when a
    released ground-truth list contains duplicate callees.
    """

    expected_lists = {
        str(caller): tuple(str(callee) for callee in callees)
        for caller, callees in expected.items()
    }
    predicted: dict[str, set[str]] = {}
    for caller, callee in predicted_edges:
        predicted.setdefault(caller, set()).add(callee)

    precision_total = len(predicted_edges)
    precision_caught = sum(
        1
        for caller, callee in predicted_edges
        if callee in expected_lists.get(caller, ())
    )
    recall_total = sum(len(callees) for callees in expected_lists.values())
    recall_caught = sum(
        1
        for caller, callees in expected_lists.items()
        for callee in callees
        if callee in predicted.get(caller, set())
    )
    return EdgeScore(
        true_positive=precision_caught,
        false_positive=precision_total - precision_caught,
        false_negative=recall_total - recall_caught,
        recall_true_positive=recall_caught,
    )


def _add_scores(left: EdgeScore, right: EdgeScore) -> EdgeScore:
    left_recall_tp = (
        left.true_positive
        if left.recall_true_positive is None
        else left.recall_true_positive
    )
    right_recall_tp = (
        right.true_positive
        if right.recall_true_positive is None
        else right.recall_true_positive
    )
    recall_true_positive = left_recall_tp + right_recall_tp
    true_positive = left.true_positive + right.true_positive
    return EdgeScore(
        true_positive=true_positive,
        false_positive=left.false_positive + right.false_positive,
        false_negative=left.false_negative + right.false_negative,
        recall_true_positive=(
            recall_true_positive
            if recall_true_positive != true_positive
            else None
        ),
    )


@dataclass(frozen=True)
class MacroProjectSpec:
    name: str
    package_root_parts: tuple[str, ...]
    file_root_parts: tuple[str, ...]
    exclude_tests: bool = False
    exclude_setup_py: bool = False


_MACRO_PROJECTS: tuple[MacroProjectSpec, ...] = (
    MacroProjectSpec(
        name="autojump",
        package_root_parts=("autojump", "bin"),
        file_root_parts=("autojump", "bin"),
    ),
    MacroProjectSpec(
        name="fabric",
        package_root_parts=("fabric",),
        file_root_parts=("fabric",),
        exclude_tests=True,
        exclude_setup_py=True,
    ),
    MacroProjectSpec(
        name="asciinema",
        package_root_parts=("asciinema",),
        file_root_parts=("asciinema", "asciinema"),
    ),
    MacroProjectSpec(
        name="face_classification",
        package_root_parts=("face_classification", "src"),
        file_root_parts=("face_classification", "src"),
    ),
    MacroProjectSpec(
        name="Sublist3r",
        package_root_parts=("Sublist3r",),
        file_root_parts=("Sublist3r",),
    ),
)


def load_cases(
    corpus_root: Path,
    *,
    suite: str = "micro",
    limit: int | None = None,
) -> tuple[PyCGCase, ...]:
    if suite == "micro":
        return load_micro_cases(corpus_root, limit=limit)
    if suite == "macro":
        return load_macro_cases(corpus_root, limit=limit)
    raise ValueError(f"unknown PyCG suite: {suite}")


def load_micro_cases(corpus_root: Path, *, limit: int | None = None) -> tuple[PyCGCase, ...]:
    snippet_root = corpus_root / "micro-benchmark" / "snippets"
    if not snippet_root.is_dir():
        raise FileNotFoundError(
            "PyCG corpus root must contain micro-benchmark/snippets: "
            f"{corpus_root}"
        )
    cases: list[PyCGCase] = []
    for case_root in sorted(path for path in snippet_root.glob("*/*") if path.is_dir()):
        main_path = case_root / "main.py"
        callgraph_path = case_root / "callgraph.json"
        if not main_path.is_file() or not callgraph_path.is_file():
            continue
        expected_json = json.loads(callgraph_path.read_text(encoding="utf-8"))
        expected = {
            str(caller): tuple(str(callee) for callee in callees)
            for caller, callees in expected_json.items()
        }
        cases.append(
            PyCGCase(
                suite="micro",
                suite_path=str(case_root.relative_to(snippet_root)),
                root=case_root,
                package_root=case_root,
                main_path=main_path,
                source_paths=tuple(sorted(case_root.rglob("*.py"))),
                expected=expected,
            )
        )
        if limit is not None and len(cases) >= limit:
            break
    return tuple(cases)


def load_macro_cases(corpus_root: Path, *, limit: int | None = None) -> tuple[PyCGCase, ...]:
    macro_root = _resolve_macro_root(corpus_root)
    projects_root = macro_root / "projects"
    ground_truth_root = macro_root / "ground-truth-cgs"
    if not projects_root.is_dir() or not ground_truth_root.is_dir():
        raise FileNotFoundError(
            "PyCG macro corpus root must contain projects/ and ground-truth-cgs/: "
            f"{corpus_root}"
        )

    cases: list[PyCGCase] = []
    for spec in _MACRO_PROJECTS:
        package_root = projects_root.joinpath(*spec.package_root_parts)
        file_root = projects_root.joinpath(*spec.file_root_parts)
        ground_truth_path = ground_truth_root / f"{spec.name}.json"
        if not package_root.is_dir():
            raise FileNotFoundError(f"PyCG macro package root not found: {package_root}")
        if not file_root.is_dir():
            raise FileNotFoundError(f"PyCG macro file root not found: {file_root}")
        if not ground_truth_path.is_file():
            raise FileNotFoundError(f"PyCG macro ground truth not found: {ground_truth_path}")

        expected_json = json.loads(ground_truth_path.read_text(encoding="utf-8"))
        expected = {
            str(caller): tuple(str(callee) for callee in callees)
            for caller, callees in expected_json.items()
        }
        source_paths = tuple(
            path
            for path in sorted(file_root.rglob("*.py"))
            if _macro_file_is_included(path, spec)
        )
        cases.append(
            PyCGCase(
                suite="macro",
                suite_path=spec.name,
                root=projects_root / spec.name,
                package_root=package_root,
                main_path=source_paths[0] if source_paths else file_root,
                source_paths=source_paths,
                expected=expected,
            )
        )
        if limit is not None and len(cases) >= limit:
            break
    return tuple(cases)


def _resolve_macro_root(corpus_root: Path) -> Path:
    if (corpus_root / "data" / "macro-benchmark").is_dir():
        return corpus_root / "data" / "macro-benchmark"
    return corpus_root


def _macro_file_is_included(path: Path, spec: MacroProjectSpec) -> bool:
    path_text = path.as_posix()
    if spec.exclude_setup_py and "setup.py" in path_text:
        return False
    if spec.exclude_tests and "tests" in path_text:
        return False
    return True


def run_archway_pycg(
    *,
    corpus_root: Path,
    engine_root: Path,
    suite: str = "micro",
    limit: int | None = None,
    case_names: tuple[str, ...] = (),
    include_diagnostic_name_hints: bool = False,
    analysis_product: str = "standalone",
    callable_root_activation: str = "off",
    case_timeout_seconds: float | None = None,
    edge_provider: EdgeProvider = "successor",
    successor_record_events: bool = False,
    successor_summarize_callee_results: bool = False,
    successor_sampling_rate_hz: float | None = None,
    successor_partial_graph_checkpoint_seconds: float | None = None,
) -> PyCGRunResult:
    if case_timeout_seconds is not None and case_timeout_seconds <= 0:
        raise ValueError("--case-timeout-seconds must be positive")
    if (
        successor_sampling_rate_hz is not None
        and successor_sampling_rate_hz <= 0
    ):
        raise ValueError("--successor-sampling-rate-hz must be positive")
    if (
        successor_partial_graph_checkpoint_seconds is not None
        and successor_partial_graph_checkpoint_seconds <= 0
    ):
        raise ValueError(
            "--successor-partial-graph-checkpoint-seconds must be positive"
        )
    if case_names and limit is not None:
        raise ValueError("--case and --limit are mutually exclusive")
    cases = load_cases(corpus_root, suite=suite, limit=limit)
    if case_names:
        requested = set(case_names)
        cases = tuple(
            case for case in cases if case.suite_path in requested
        )
        missing = requested - {case.suite_path for case in cases}
        if missing:
            raise ValueError(f"unknown PyCG cases: {sorted(missing)}")
    started = time.perf_counter()
    results: list[PyCGCaseResult] = []
    total = EdgeScore(0, 0, 0)
    predicted_total = 0
    expected_total = 0

    for index, case in enumerate(cases, start=1):
        case_started = time.perf_counter()
        print(
            f"PyCG {suite} case {index}/{len(cases)} {case.suite_path}: "
            f"start elapsed={case_started - started:.3f}s",
            file=sys.stderr,
            flush=True,
        )
        expected = set(case.expected_edges)
        expected_total += case.expected_edge_occurrence_count
        try:
            produced = _archway_call_edges_with_timeout(
                case,
                engine_root=engine_root,
                include_diagnostic_name_hints=include_diagnostic_name_hints,
                analysis_product=analysis_product,
                callable_root_activation=callable_root_activation,
                case_timeout_seconds=case_timeout_seconds,
                edge_provider=edge_provider,
                successor_record_events=successor_record_events,
                successor_summarize_callee_results=(
                    successor_summarize_callee_results
                ),
                successor_sampling_rate_hz=successor_sampling_rate_hz,
                successor_partial_graph_checkpoint_seconds=(
                    successor_partial_graph_checkpoint_seconds
                ),
            )
            if isinstance(produced, SuccessorEdgeResult):
                predicted = set(produced.edges)
                analysis_evidence = produced.evidence
            else:
                predicted = produced
                analysis_evidence = {}
            status = "ok"
            error = None
        except TimeoutError as exc:
            predicted = set()
            status = "timeout"
            error = str(exc)
            analysis_evidence = getattr(exc, "analysis_evidence", {})
        except Exception as exc:
            predicted = set()
            status = "error"
            error = f"{type(exc).__name__}: {exc}"
            analysis_evidence = getattr(exc, "analysis_evidence", {})
        score = score_adjacency_lists(case.expected, predicted)
        total = _add_scores(total, score)
        predicted_total += len(predicted)
        case_elapsed = time.perf_counter() - case_started
        results.append(
            PyCGCaseResult(
                suite_path=case.suite_path,
                expected_edge_count=case.expected_edge_occurrence_count,
                predicted_edge_count=len(predicted),
                score=score,
                status=status,
                error=error,
                elapsed_seconds=case_elapsed,
                predicted_edges=tuple(sorted(predicted)),
                missing_edges=tuple(sorted(expected - predicted)),
                extra_edges=tuple(sorted(predicted - expected)),
                analysis_evidence=analysis_evidence,
            )
        )
        print(
            f"PyCG {suite} case {index}/{len(cases)} {case.suite_path}: "
            f"{status} case_elapsed={case_elapsed:.3f}s "
            f"elapsed={time.perf_counter() - started:.3f}s "
            f"predicted_edges={len(predicted)}",
            file=sys.stderr,
            flush=True,
        )

    return PyCGRunResult(
        suite=suite,
        corpus_root=str(corpus_root),
        engine_root=str(engine_root),
        edge_provider=edge_provider,
        cases_total=len(cases),
        cases_attempted=len(cases),
        cases_ok=sum(1 for result in results if result.status == "ok"),
        cases_error=sum(1 for result in results if result.status != "ok"),
        expected_edges_total=expected_total,
        predicted_edges_total=predicted_total,
        score=total,
        elapsed_seconds=time.perf_counter() - started,
        cases=tuple(results),
        project_scores={
            result.suite_path: result.score.to_jsonable()
            | {
                "expected_edge_count": result.expected_edge_count,
                "predicted_edge_count": result.predicted_edge_count,
            }
            for result in results
        },
    )


def _archway_call_edges_with_timeout(
    case: PyCGCase,
    *,
    engine_root: Path,
    include_diagnostic_name_hints: bool,
    analysis_product: str,
    callable_root_activation: str,
    case_timeout_seconds: float | None,
    edge_provider: EdgeProvider,
    successor_record_events: bool,
    successor_summarize_callee_results: bool,
    successor_sampling_rate_hz: float | None = None,
    successor_partial_graph_checkpoint_seconds: float | None = None,
) -> set[Edge] | SuccessorEdgeResult:
    if case_timeout_seconds is None:
        return _produce_archway_call_edges(
            case,
            engine_root=engine_root,
            include_diagnostic_name_hints=include_diagnostic_name_hints,
            analysis_product=analysis_product,
            callable_root_activation=callable_root_activation,
            edge_provider=edge_provider,
            successor_record_events=successor_record_events,
            successor_summarize_callee_results=(
                successor_summarize_callee_results
            ),
            successor_sampling_rate_hz=successor_sampling_rate_hz,
            successor_partial_graph_checkpoint_seconds=(
                successor_partial_graph_checkpoint_seconds
            ),
        )
    if case_timeout_seconds <= 0:
        raise ValueError("--case-timeout-seconds must be positive")

    ctx = _multiprocessing_context()
    result_queue = ctx.Queue()
    process = ctx.Process(
        target=_archway_call_edges_worker,
        args=(
            result_queue,
            case,
            engine_root,
            include_diagnostic_name_hints,
            analysis_product,
            callable_root_activation,
            edge_provider,
            successor_record_events,
            successor_summarize_callee_results,
            successor_sampling_rate_hz,
            successor_partial_graph_checkpoint_seconds,
        ),
    )
    process.start()
    deadline = time.monotonic() + case_timeout_seconds
    latest_evidence: dict[str, object] = {}
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _stop_case_worker(process)
            while True:
                try:
                    status, payload = result_queue.get_nowait()
                except queue.Empty:
                    break
                if status == "progress":
                    latest_evidence.update(payload)
            raise PyCGCaseTimeoutError(
                f"case exceeded timeout of {case_timeout_seconds:.3f}s",
                latest_evidence,
            )
        try:
            status, payload = result_queue.get(timeout=min(1.0, remaining))
        except queue.Empty:
            if process.is_alive():
                continue
            raise RuntimeError(
                "case worker exited without returning a result; "
                f"exitcode={process.exitcode}"
            )
        if status == "progress":
            # Progress messages intentionally have different costs and
            # cadences.  Preserve the most recent expensive checkpoint when a
            # later cheap aggregate sample arrives.
            latest_evidence.update(payload)
            continue
        process.join()
        if status == "ok":
            return payload
        error, evidence = payload
        raise PyCGCaseExecutionError(error, evidence or latest_evidence)


def _stop_case_worker(
    process: multiprocessing.Process,
    *,
    terminate_grace_seconds: float = 0.5,
    kill_grace_seconds: float = 1.0,
) -> None:
    """Stop a timed-out worker without turning a case bound into an unbounded wait."""

    process.terminate()
    process.join(timeout=terminate_grace_seconds)
    if not process.is_alive():
        return
    process.kill()
    process.join(timeout=kill_grace_seconds)
    if process.is_alive():
        raise RuntimeError(
            "timed-out case worker remained alive after terminate and kill"
        )


def _multiprocessing_context() -> multiprocessing.context.BaseContext:
    methods = multiprocessing.get_all_start_methods()
    if "fork" in methods:
        return multiprocessing.get_context("fork")
    return multiprocessing.get_context()


def _archway_call_edges_worker(
    result_queue: multiprocessing.queues.Queue,
    case: PyCGCase,
    engine_root: Path,
    include_diagnostic_name_hints: bool,
    analysis_product: str,
    callable_root_activation: str,
    edge_provider: EdgeProvider,
    successor_record_events: bool,
    successor_summarize_callee_results: bool,
    successor_sampling_rate_hz: float | None = None,
    successor_partial_graph_checkpoint_seconds: float | None = None,
) -> None:
    try:
        predicted = _produce_archway_call_edges(
            case,
            engine_root=engine_root,
            include_diagnostic_name_hints=include_diagnostic_name_hints,
            analysis_product=analysis_product,
            callable_root_activation=callable_root_activation,
            edge_provider=edge_provider,
            successor_record_events=successor_record_events,
            successor_summarize_callee_results=(
                successor_summarize_callee_results
            ),
            successor_sampling_rate_hz=successor_sampling_rate_hz,
            successor_partial_graph_checkpoint_seconds=(
                successor_partial_graph_checkpoint_seconds
            ),
            successor_progress=(
                lambda evidence: result_queue.put(("progress", evidence))
            ),
        )
    except Exception as exc:
        result_queue.put(("error", (
            f"{type(exc).__name__}: {exc}",
            getattr(exc, "analysis_evidence", {}),
        )))
    else:
        result_queue.put(("ok", predicted))


def _produce_archway_call_edges(
    case: PyCGCase,
    *,
    engine_root: Path,
    include_diagnostic_name_hints: bool,
    analysis_product: str,
    callable_root_activation: str,
    edge_provider: EdgeProvider,
    successor_record_events: bool,
    successor_summarize_callee_results: bool,
    successor_sampling_rate_hz: float | None = None,
    successor_partial_graph_checkpoint_seconds: float | None = None,
    successor_progress: Callable[[dict[str, object]], None] | None = None,
) -> set[Edge] | SuccessorEdgeResult:
    if edge_provider == "successor":
        return successor_archway_call_edge_result(
            case,
            engine_root=engine_root,
            record_events=successor_record_events,
            progress=successor_progress,
            summarize_callee_results=successor_summarize_callee_results,
            sampling_rate_hz=successor_sampling_rate_hz,
            partial_graph_checkpoint_seconds=(
                successor_partial_graph_checkpoint_seconds
            ),
        )
    if edge_provider == "coordinated":
        return coordinated_archway_call_edges(case, engine_root=engine_root)
    if edge_provider == "legacy":
        return archway_call_edges(
            case,
            engine_root=engine_root,
            include_diagnostic_name_hints=include_diagnostic_name_hints,
            analysis_product=analysis_product,
            callable_root_activation=callable_root_activation,
        )
    raise ValueError(f"unknown edge provider: {edge_provider}")


def successor_archway_call_edges(
    case: PyCGCase,
    *,
    engine_root: Path,
) -> set[Edge]:
    """Project only diagram-successor call-target facts into PyCG edges."""

    return set(successor_archway_call_edge_result(
        case, engine_root=engine_root
    ).edges)


def successor_archway_call_edge_result(
    case: PyCGCase,
    *,
    engine_root: Path,
    record_events: bool = False,
    progress: Callable[[dict[str, object]], None] | None = None,
    summarize_callee_results: bool = False,
    sampling_rate_hz: float | None = None,
    partial_graph_checkpoint_seconds: float | None = None,
) -> SuccessorEdgeResult:
    """Project one persistent diagram-only reduced-product program session."""

    if not engine_root.exists():
        raise FileNotFoundError(f"engine root not found: {engine_root}")
    engine_text = str(engine_root)
    if engine_text not in sys.path:
        sys.path.insert(0, engine_text)

    from sd_core.analysis.diagram_analysis import open_hybrid_program_session
    from sd_core.tooling.harness import ProgramResult
    from sd_core.tooling.sampling_profile import SamplingProfiler

    started = time.perf_counter()
    sources = _load_case_sources(case)
    translation_started = time.perf_counter()
    program = ProgramResult.from_sources(sources)
    translation_seconds = time.perf_counter() - translation_started
    modules = {
        name: translation.morphism
        for name, translation in program.modules.items()
    }
    entry_module = "main" if "main" in modules else min(modules)
    session = open_hybrid_program_session(
        modules,
        entry_module,
        record_events=record_events,
        possible_entry_modules=(
            frozenset(modules) if case.suite == "macro" else None
        ),
    )
    topology_before = session.scheduler.graph.topology_generation
    analysis_started = time.perf_counter()
    include_callable_bodies = case.suite == "macro"
    stop_sampling = threading.Event()
    root_labels = {
        address.id: f"module:{name}"
        for name, address in session.module_roots.items()
    }
    root_labels.update({
        address.id: "callable:" + (
            session.callable_boundaries_by_body[body_id].display_name
            if body_id in session.callable_boundaries_by_body
            else name
        )
        for name, address in session.callable_roots.items()
        if (body_id := getattr(address.subject, "body_morphism_id", None))
    })
    body_labels = {
        body_id: (
            session.callable_boundaries_by_body[body_id].display_name
            if body_id in session.callable_boundaries_by_body
            else name
        )
        for name, address in session.callable_roots.items()
        if (body_id := getattr(address.subject, "body_morphism_id", None))
    }
    sampling_profile = None

    def current_evidence(*, phase: str) -> dict[str, object]:
        snapshot = session.store.snapshot()
        family_counts: dict[str, int] = {}
        for address in snapshot.resolved_facts:
            family_counts[address.family] = (
                family_counts.get(address.family, 0) + 1
            )
        production_counts = session.scheduler.production_counts
        production_seconds = session.scheduler.production_seconds
        production_change_counts = session.scheduler.production_change_counts
        production_growth_counts = (
            session.scheduler.production_growth_coordinate_counts
        )

        def growth_for(key) -> dict[str, int]:
            return dict(sorted(
                (
                    (coordinate, count)
                    for (production, coordinate), count
                    in production_growth_counts.items()
                    if production == key
                ),
                key=lambda item: item[0],
            ))

        boundaries_by_definition = {
            boundary.definition_morphism_id: boundary
            for boundary in session.callable_boundaries_by_body.values()
        }

        def invocation_request_for(key):
            registry = session.invocation_registry
            return (
                registry.requests.get(key.address)
                if registry is not None else None
            )

        def callable_for(key) -> str | None:
            owner = session.callable_owner_for(
                key.address.context,
                getattr(key.address.subject, "morphism_id", ""),
            )
            if owner is not None:
                return owner.display_name
            body_id = getattr(
                key.address.subject, "body_morphism_id", None
            )
            if body_id in body_labels:
                return body_labels[body_id]
            request = invocation_request_for(key)
            if request is None:
                return None
            boundary = boundaries_by_definition.get(
                request.value.definition_morphism_id
            )
            return boundary.display_name if boundary is not None else None

        def callable_value_for(key) -> dict[str, object] | None:
            request = invocation_request_for(key)
            return (
                dict(request.value.canonical_data())
                if request is not None else None
            )

        hottest_productions = [
            {
                "address_id": key.address.id,
                "family": key.address.family,
                "subject": key.address.subject.canonical_data(),
                "callable": callable_for(key),
                "callable_value": callable_value_for(key),
                "context": key.address.context,
                "provider_id": key.provider_id,
                "executions": executions,
                "seconds": production_seconds.get(key, 0.0),
                "value_changes": production_change_counts.get(key, 0),
                "growth_coordinates": growth_for(key),
            }
            for key, executions in sorted(
                production_counts.items(),
                key=lambda item: (-item[1], item[0].id),
            )[:20]
        ]
        slowest_productions = [
            {
                "address_id": key.address.id,
                "family": key.address.family,
                "subject": key.address.subject.canonical_data(),
                "callable": callable_for(key),
                "callable_value": callable_value_for(key),
                "context": key.address.context,
                "provider_id": key.provider_id,
                "seconds": seconds,
                "executions": production_counts.get(key, 0),
                "value_changes": production_change_counts.get(key, 0),
            }
            for key, seconds in sorted(
                production_seconds.items(),
                key=lambda item: (-item[1], item[0].id),
            )[:20]
        ]
        hottest_transfers = sorted(
            (
                {
                    "morphism_id": morphism_id,
                    "operation": operation,
                    "visits": visits,
                }
                for (morphism_id, operation), visits
                in session.scheduler.transfer_counts.items()
            ),
            key=lambda item: (-item["visits"], item["morphism_id"], item["operation"]),
        )[:20]
        hottest_transfer_seconds = sorted(
            (
                {
                    "morphism_id": morphism_id,
                    "operation": operation,
                    "seconds": seconds,
                    "visits": session.scheduler.transfer_counts.get(
                        (morphism_id, operation), 0
                    ),
                }
                for (morphism_id, operation), seconds
                in session.scheduler.transfer_seconds.items()
            ),
            key=lambda item: (
                -item["seconds"], item["morphism_id"], item["operation"]
            ),
        )[:20]
        scheduler_event_counts = {
            kind.value: count
            for kind, count in session.scheduler.event_counts.items()
        }
        query_progress = session.scheduler.query_progress
        completed_root_seconds = query_progress["completed_root_seconds"]
        try:
            components = session.scheduler.graph.components()
            recursive_components = sum(
                session.scheduler.graph.is_recursive(component)
                for component in components
            )
        except RuntimeError:
            components = ()
            recursive_components = 0
        component_sizes = sorted(
            (len(component.members) for component in components),
            reverse=True,
        )
        nodes_by_key = {
            node.key: node for node in session.scheduler.graph.nodes
        }
        recursive_component_details = [
            {
                "component_id": component.id,
                "size": len(component.members),
                "members": [
                    {
                        "family": key.address.family,
                        "address_id": key.address.id,
                        "provider_id": key.provider_id,
                        "context": key.address.context,
                        "projection": key.address.projection,
                        "prerequisites": [
                            {
                                "family": prerequisite.family,
                                "address_id": prerequisite.id,
                                "context": prerequisite.context,
                                "projection": prerequisite.projection,
                            }
                            for prerequisite in sorted(
                                nodes_by_key[key].prerequisites,
                                key=lambda item: item.id,
                            )
                        ],
                        "morphism_id": getattr(
                            key.address.subject, "morphism_id", None
                        ),
                        "callable": (
                            owner.display_name
                            if (owner := session.callable_owner_for(
                                key.address.context,
                                getattr(
                                    key.address.subject, "morphism_id", ""
                                )
                            )) is not None
                            else body_labels.get(getattr(
                                key.address.subject,
                                "body_morphism_id",
                                None,
                            ))
                        ),
                        "executions": production_counts.get(key, 0),
                        "value_changes": production_change_counts.get(key, 0),
                        "growth_coordinates": growth_for(key),
                    }
                    for key in component.members
                ],
            }
            for component in sorted(
                (
                    component for component in components
                    if session.scheduler.graph.is_recursive(component)
                ),
                key=lambda item: (-len(item.members), item.id),
            )[:5]
        ]
        production_execution_count = sum(production_counts.values())
        repeated_production_count = sum(
            count - 1
            for count in production_counts.values()
            if count > 1
        )
        module_names = sorted(modules)
        callable_root_names = sorted(session.callable_roots)
        evidence = {
            "phase": phase,
            "source_module_count": len(sources),
            "translated_module_count": len(modules),
            "module_roots": module_names,
            "module_closure": {
                "policy": "translated-corpus-program",
                "count": len(module_names),
                "modules": module_names,
            },
            "root_inventory": {
                "module_count": len(session.module_roots),
                "module_names": sorted(session.module_roots),
                "callable_body_count": len(callable_root_names),
                "callable_body_names": callable_root_names,
            },
            "callable_body_root_count": (
                len(session.callable_roots) if include_callable_bodies else 0
            ),
            "root_policy": (
                "all_modules_possible_entries_and_callable_bodies"
                if include_callable_bodies else "all_modules"
            ),
            "callee_result_policy": (
                "compositional_summary"
                if summarize_callee_results else "precise_invocation"
            ),
            "root_demand_count": scheduler_event_counts.get("root_demand", 0),
            "active_root": (
                root_labels.get(query_progress["active_root_id"],
                                query_progress["active_root_id"])
            ),
            "active_root_seconds": query_progress["active_root_seconds"],
            "completed_root_count": query_progress["completed_root_count"],
            "completed_root_seconds_total": query_progress[
                "completed_root_seconds_total"
            ],
            "completed_root_history_truncated": query_progress[
                "completed_root_history_truncated"
            ],
            "completed_root_seconds": [
                {
                    "root": root_labels.get(root_id, root_id),
                    "seconds": seconds,
                }
                for root_id, seconds in completed_root_seconds
            ],
            "slowest_completed_roots": [
                {
                    "root": root_labels.get(root_id, root_id),
                    "seconds": seconds,
                }
                for root_id, seconds
                in query_progress["slowest_completed_roots"]
            ],
            "invocation_context_counts": session.invocation_context_counts(),
            "invocation_input_growth_counts": (
                session.invocation_input_growth_counts()
            ),
            "invocation_admission_counts": (
                session.invocation_admission_counts()
            ),
            "invocation_summary_telemetry": (
                session.invocation_summary_telemetry()
            ),
            "deferred_materialization_counts": (
                session.deferred_materialization_counts()
            ),
            "resolved_fact_count": len(snapshot.resolved_facts),
            "fact_family_counts": dict(sorted(family_counts.items())),
            "demand_node_count": session.scheduler.graph.node_count,
            "scc_count": len(components),
            "recursive_scc_count": recursive_components,
            "recursive_scc_details": recursive_component_details,
            "largest_scc_size": component_sizes[0] if component_sizes else 0,
            "scc_size_histogram": dict(sorted(Counter(
                component_sizes
            ).items())),
            "topology_generation": (
                session.scheduler.graph.topology_generation
            ),
            "scc_recompute_count": (
                session.scheduler.graph.component_recompute_count
            ),
            "scc_recompute_seconds": (
                session.scheduler.graph.component_recompute_seconds
            ),
            "scc_recompute_node_visits": (
                session.scheduler.graph.component_node_visits
            ),
            "scc_recompute_edge_visits": (
                session.scheduler.graph.component_edge_visits
            ),
            "scc_incremental_refresh_count": (
                session.scheduler.graph.component_incremental_refresh_count
            ),
            "production_event_count": sum(scheduler_event_counts.values()),
            "scheduler_event_counts": dict(sorted(
                scheduler_event_counts.items()
            )),
            "invalidation_reason_counts": dict(sorted(
                session.scheduler.invalidation_reason_counts.items()
            )),
            "unique_production_count": len(production_counts),
            "production_execution_count": production_execution_count,
            "production_value_change_count": sum(
                production_change_counts.values()
            ),
            "repeated_production_count": repeated_production_count,
            "repeated_production_ratio": (
                repeated_production_count / production_execution_count
                if production_execution_count else 0.0
            ),
            "hottest_productions": hottest_productions,
            "slowest_productions": slowest_productions,
            "hottest_transfers": hottest_transfers,
            "hottest_transfer_seconds": hottest_transfer_seconds,
            "transfer_operation_counts": dict(sorted(
                session.scheduler.transfer_operation_counts.items()
            )),
            "transfer_operation_seconds": dict(sorted(
                session.scheduler.transfer_operation_seconds.items()
            )),
            "morphism_transfer_reuse_counts": (
                session.morphism_transfer_reuse_counts()
            ),
            "module_export_summary_count": family_counts.get(
                "ModuleExportSummary", 0
            ),
            "module_semantic_summary_count": family_counts.get(
                "ModuleSemanticSummary", 0
            ),
            "summary_cache_hit_count": session.scheduler.summary_cache_hits,
            "summary_reuse": {
                "cache_hit_count": session.scheduler.summary_cache_hits,
                "module_export_summary_count": family_counts.get(
                    "ModuleExportSummary", 0
                ),
                "module_semantic_summary_count": family_counts.get(
                    "ModuleSemanticSummary", 0
                ),
                "registered_invocation_summary_count": (
                    session.invocation_context_counts().get(
                        "summary_registered", 0
                    )
                ),
            },
            "knowledge_commit_counts": session.store.commit_counts,
            "translation_seconds": translation_seconds,
            "analysis_seconds": time.perf_counter() - analysis_started,
            "total_provider_seconds": time.perf_counter() - started,
            "trace_events_enabled": record_events,
            "progress_sample_seconds": progress_sample_seconds,
            "peak_rss_bytes": (
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                * (1024 if sys.platform.startswith("linux") else 1)
            ),
        }
        if sampling_profile is not None:
            evidence["sampling_profile"] = sampling_profile.jsonable(top=50)
        return evidence

    # Cheap aggregate progress is part of the case-timeout contract, independent
    # of whether statistical stack sampling is enabled.  Keeping one cadence
    # makes bounded profiled and unprofiled checkpoints directly comparable.
    progress_sample_seconds = 5.0

    def current_partial_graph_evidence() -> dict[str, object]:
        """Project a diagnostic graph without claiming scheduler convergence."""

        projection_started = time.perf_counter()
        semantic_edges = session.semantic_call_edges()
        direct_edges = {
            (
                edge.caller.display_name
                if edge.caller is not None
                else edge.caller_module,
                _successor_pycg_target_name(edge.target.display_name),
            )
            for edge in semantic_edges
            if edge.caller is not None or edge.caller_module is not None
        }
        projected_edges, _lineage = _inline_synthetic_frame_edges_with_evidence(
            direct_edges
        )
        score = score_adjacency_lists(case.expected, projected_edges)
        expected_edges = set(case.expected_edges)
        return {
            "partial_semantic_graph": {
                "converged": False,
                "analysis_seconds": time.perf_counter() - analysis_started,
                "projection_seconds": time.perf_counter() - projection_started,
                "semantic_direct_edge_count": len(direct_edges),
                "pycg_projected_edge_count": len(projected_edges),
                "score": score.to_jsonable(),
                "predicted_edges": [
                    list(edge) for edge in sorted(projected_edges)
                ],
                "missing_edges": [
                    list(edge)
                    for edge in sorted(expected_edges - projected_edges)
                ],
                "extra_edges": [
                    list(edge) for edge in sorted(projected_edges - expected_edges)
                ],
            }
        }

    def current_progress_evidence() -> dict[str, object]:
        """Return a bounded live sample without traversing retained facts."""

        collection_started = time.perf_counter()
        production = session.scheduler.aggregate_production_telemetry
        production_execution_count = int(
            production["production_execution_count"]
        )
        repeated_production_count = int(
            production["repeated_production_count"]
        )
        query_progress = session.scheduler.query_progress

        def top_counts(values: Counter[str]) -> dict[str, int | float]:
            return dict(values.most_common(20))

        evidence: dict[str, object] = {
            "phase": "analysis",
            "evidence_detail": "live-aggregate",
            "analysis_seconds": time.perf_counter() - analysis_started,
            "demand_node_count": session.scheduler.graph.node_count,
            "topology_generation": (
                session.scheduler.graph.topology_generation
            ),
            "scc_recompute_count": (
                session.scheduler.graph.component_recompute_count
            ),
            "scc_recompute_seconds": (
                session.scheduler.graph.component_recompute_seconds
            ),
            "scc_recompute_node_visits": (
                session.scheduler.graph.component_node_visits
            ),
            "scc_recompute_edge_visits": (
                session.scheduler.graph.component_edge_visits
            ),
            "scc_incremental_refresh_count": (
                session.scheduler.graph.component_incremental_refresh_count
            ),
            "active_root": root_labels.get(
                query_progress["active_root_id"],
                query_progress["active_root_id"],
            ),
            "active_root_seconds": query_progress["active_root_seconds"],
            "completed_root_count": query_progress["completed_root_count"],
            "completed_root_seconds_total": query_progress[
                "completed_root_seconds_total"
            ],
            "completed_root_history_truncated": query_progress[
                "completed_root_history_truncated"
            ],
            "completed_root_seconds": [
                {
                    "root": root_labels.get(root_id, root_id),
                    "seconds": seconds,
                }
                for root_id, seconds
                in query_progress["completed_root_seconds"]
            ],
            "slowest_completed_roots": [
                {
                    "root": root_labels.get(root_id, root_id),
                    "seconds": seconds,
                }
                for root_id, seconds
                in query_progress["slowest_completed_roots"]
            ],
            "scheduler_event_counts": dict(sorted(
                (kind.value, count)
                for kind, count in session.scheduler.event_counts.items()
            )),
            "invalidation_reason_counts": dict(sorted(
                session.scheduler.invalidation_reason_counts.items()
            )),
            "unique_production_count": production[
                "unique_production_count"
            ],
            "production_execution_count": production_execution_count,
            "repeated_production_count": repeated_production_count,
            "repeated_production_ratio": (
                repeated_production_count / production_execution_count
                if production_execution_count else 0.0
            ),
            "production_executions_by_family": top_counts(
                Counter(production["production_executions_by_family"])
            ),
            "production_repeats_by_family": top_counts(
                Counter(production["production_repeats_by_family"])
            ),
            "production_seconds_by_family": top_counts(
                Counter(production["production_seconds_by_family"])
            ),
            "production_executions_by_provider": top_counts(
                Counter(production["production_executions_by_provider"])
            ),
            "transfer_operation_counts": dict(sorted(
                session.scheduler.transfer_operation_counts.items()
            )),
            "transfer_operation_seconds": dict(sorted(
                session.scheduler.transfer_operation_seconds.items()
            )),
            "morphism_transfer_reuse_counts": (
                session.morphism_transfer_reuse_counts()
            ),
            "peak_rss_bytes": (
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                * (1024 if sys.platform.startswith("linux") else 1)
            ),
        }
        if sampling_profile is not None:
            evidence["sampling_profile"] = sampling_profile.jsonable(top=50)
        evidence["diagnostic_collection_seconds"] = (
            time.perf_counter() - collection_started
        )
        return evidence

    def sample_progress() -> None:
        assert progress is not None
        last_partial_graph_checkpoint = analysis_started
        while not stop_sampling.wait(progress_sample_seconds):
            try:
                evidence = current_progress_evidence()
                now = time.perf_counter()
                if (
                    partial_graph_checkpoint_seconds is not None
                    and now - last_partial_graph_checkpoint
                    >= partial_graph_checkpoint_seconds
                ):
                    evidence.update(current_partial_graph_evidence())
                    last_partial_graph_checkpoint = now
                progress(evidence)
            except Exception as exc:
                progress({
                    "phase": "progress_error",
                    "evidence_detail": "live-aggregate",
                    "analysis_seconds": time.perf_counter() - analysis_started,
                    "error": f"{type(exc).__name__}: {exc}",
                })

    sampler = None
    if progress is not None:
        progress(current_evidence(phase="session_opened"))
        sampler = threading.Thread(target=sample_progress, daemon=True)
        sampler.start()
    profile_context = (
        SamplingProfiler(rate_hz=sampling_rate_hz, project_marker="/sd_core/")
        if sampling_rate_hz is not None else nullcontext()
    )
    try:
        with profile_context as sampling_profile:
            forward = session.run_semantic_call_graph(
                include_callable_bodies=include_callable_bodies,
                summarize_callee_results=summarize_callee_results,
            )
    except Exception as exc:
        evidence = current_evidence(phase="error")
        if progress is not None:
            progress(evidence)
        raise PyCGCaseExecutionError(
            f"{type(exc).__name__}: {exc}", evidence
        ) from exc
    finally:
        stop_sampling.set()
        if sampler is not None:
            sampler.join(timeout=1.0)
    analysis_seconds = time.perf_counter() - analysis_started
    semantic_edges = session.semantic_call_edges()
    edges = {
        (
            edge.caller.display_name
            if edge.caller is not None
            else edge.caller_module,
            _successor_pycg_target_name(edge.target.display_name),
        )
        for edge in semantic_edges
        if edge.caller is not None or edge.caller_module is not None
    }
    projected_edges, projection_lineage = (
        _inline_synthetic_frame_edges_with_evidence(edges)
    )

    semantic_edge_evidence = tuple(sorted(
        (
            _attach_source_line(
                _successor_semantic_edge_evidence(edge), sources
            )
            for edge in semantic_edges
            if edge.caller is not None or edge.caller_module is not None
        ),
        key=lambda item: (
            tuple(item["projected_edge"]),
            str(item["caller_context"]),
            str(item["callsite_morphism_id"]),
            str(item["invocation_id"]),
        ),
    ))

    evidence = current_evidence(phase="complete")
    evidence.update({
        "root_demand_count": (
            len(forward.roots) if hasattr(forward, "roots") else 1
        ),
        "retained_production_event_count": len(forward.events),
        "knowledge_delta_count": len(forward.knowledge_deltas),
        "analysis_seconds": analysis_seconds,
        "semantic_call_edge_evidence": semantic_edge_evidence,
        "semantic_call_edge_evidence_count": len(semantic_edge_evidence),
        "semantic_direct_edge_count": len(edges),
        "pycg_projection_lineage": projection_lineage,
        "pycg_projection_lineage_count": len(projection_lineage),
        "pycg_projected_edge_count": len(projected_edges),
    })
    if sampling_profile is not None:
        evidence["sampling_profile"] = sampling_profile.jsonable(top=50)
    if progress is not None:
        progress(evidence)
    return SuccessorEdgeResult(
        edges=frozenset(projected_edges),
        root_demands=(
            len(forward.roots) if hasattr(forward, "roots") else 1
        ),
        cache_hits=(
            forward.cache_hits
            if hasattr(forward, "cache_hits")
            else int(forward.cache_hit)
        ),
        production_events=len(forward.events),
        knowledge_deltas=len(forward.knowledge_deltas),
        topology_growth=(
            session.scheduler.graph.topology_generation - topology_before
        ),
        evidence=evidence,
    )


def _successor_semantic_edge_evidence(edge) -> dict[str, object]:
    """Serialize one contextual edge without consulting source or AST data."""

    caller = (
        edge.caller.display_name
        if edge.caller is not None else edge.caller_module
    )
    semantic_target = edge.target.display_name
    projected_target = _successor_pycg_target_name(semantic_target)
    anchor = edge.callsite_anchor
    module = (
        ".".join(anchor.module.parts)
        if anchor is not None and anchor.module is not None else None
    )
    position = anchor.position if anchor is not None else None
    invocation_data = edge.invocation.canonical_data()
    invocation_context = getattr(edge.invocation, "context", None)
    invocation_id = (
        invocation_context.id
        if invocation_context is not None
        else (
            f"{edge.invocation.caller_context}:"
            f"{edge.invocation.callsite_morphism_id}:"
            f"{edge.invocation.policy_id}"
        )
    )
    return {
        "semantic_edge": [caller, semantic_target],
        "projected_edge": [caller, projected_target],
        "caller_context": edge.caller_context,
        "caller_kind": (
            type(edge.caller).__name__
            if edge.caller is not None else "module"
        ),
        "callsite_morphism_id": edge.callsite_morphism_id,
        "source_module": module,
        "source_position": (
            {
                "line": position.row,
                "column": position.col,
                "end_line": position.end_row,
                "end_column": position.end_col,
            }
            if position is not None else None
        ),
        "target_kind": type(edge.target).__name__,
        "invocation_kind": type(edge.invocation).__name__,
        "invocation_id": invocation_id,
        "invocation": dict(invocation_data),
    }


def _attach_source_line(
    evidence: dict[str, object], sources: dict[str, str]
) -> dict[str, object]:
    """Attach corpus text for review without feeding source into analysis.

    Semantic edge production is complete before this diagnostic adapter runs.
    The excerpt is deliberately a single physical line: enough to inspect most
    callsites while keeping fully instrumented framework artifacts bounded.
    """

    module = evidence.get("source_module")
    position = evidence.get("source_position")
    if not isinstance(module, str) or not isinstance(position, dict):
        return evidence
    line = position.get("line")
    source = sources.get(module)
    if not isinstance(line, int) or line < 1 or source is None:
        return evidence
    lines = source.splitlines()
    if line > len(lines):
        return evidence
    return {
        **evidence,
        "source_line": lines[line - 1],
    }


def coordinated_archway_call_edges(
    case: PyCGCase,
    *,
    engine_root: Path,
) -> set[Edge]:
    """Project the demand-driven semantic graph into PyCG's edge vocabulary."""

    if not engine_root.exists():
        raise FileNotFoundError(f"engine root not found: {engine_root}")
    engine_text = str(engine_root)
    if engine_text not in sys.path:
        sys.path.insert(0, engine_text)

    from sd_core.analysis.runtime.call_targets import (
        BoundMethod,
        BuiltinBoundary,
        ClassConstruction,
        ExternalSummaryBoundary,
        LocalFunction,
    )
    from sd_core.analysis.runtime.contracts import BoundarySubject, ModuleKey
    from sd_core.analysis.runtime.semantic_call_graph import (
        EntrySeed,
        SemanticCallGraphRequest,
        SemanticCallGraphRuntime,
    )
    from sd_core.runners.contextual_call_resolution import (
        build_python_program_callable_indexes,
    )

    sources = _load_case_sources(case)
    program = build_python_program_callable_indexes(sources)
    root_modules = _coordinated_root_modules(case, sources)
    roots = tuple(
        EntrySeed(
            f"module:{module_name}",
            BoundarySubject(
                ModuleKey("workspace:program", module_name),
                f"{module_name}:<module>",
            ),
        )
        for module_name in root_modules
    )
    result = SemanticCallGraphRuntime(program).build(SemanticCallGraphRequest(
        program.revision,
        roots,
        requester=f"pycg:{case.suite}:{case.suite_path}",
    ))
    declared_initializers = {
        boundary.declaration
        for boundary, _parameters in program.signatures
        if boundary.declaration.endswith(".__init__")
    }
    edges: set[Edge] = set()
    for edge in result.edges:
        caller = _coordinated_local_display_name(edge.caller.boundary.declaration)
        target = edge.target
        if isinstance(target, (LocalFunction, BoundMethod)):
            callee = _coordinated_local_display_name(target.boundary.declaration)
        elif isinstance(target, ClassConstruction):
            initializer = f"{target.boundary.declaration}.__init__"
            callee = (
                _coordinated_local_display_name(initializer)
                if initializer in declared_initializers
                else None
            )
        elif isinstance(target, BuiltinBoundary):
            qualified = target.boundary.qualified_name.removeprefix("builtins.")
            callee = f"<builtin>.{qualified}"
        elif isinstance(target, ExternalSummaryBoundary):
            callee = target.boundary.qualified_name
        else:
            callee = None
        if callee is not None:
            edges.add((caller, callee))
    return edges


def _coordinated_root_modules(
    case: PyCGCase,
    sources: Mapping[str, str],
) -> tuple[str, ...]:
    if case.suite == "micro" and "main" in sources:
        return ("main",)
    return tuple(sorted(sources))


def _coordinated_local_display_name(declaration: str) -> str:
    module_name, local_name = declaration.split(":", 1)
    return module_name if local_name == "<module>" else f"{module_name}.{local_name}"


def archway_call_edges(
    case: PyCGCase,
    *,
    engine_root: Path,
    include_diagnostic_name_hints: bool = False,
    analysis_product: str = "standalone",
    callable_root_activation: str = "off",
    callable_root_body_ids: frozenset[str] | None = None,
) -> set[Edge]:
    """Project Archway call-relation facts to PyCG edge strings.

    This is intentionally thin. It imports the engine from ``engine_root`` and
    reads Archway's call relation. It does not parse Python source directly to
    invent edges.
    """

    if not engine_root.exists():
        raise FileNotFoundError(f"engine root not found: {engine_root}")
    engine_text = str(engine_root)
    if engine_text not in sys.path:
        sys.path.insert(0, engine_text)

    from sd_core.analysis.callloops.call_relation import project_call_relation
    from sd_core.analysis.callloops.runner import analyze_morphism
    from sd_core.runners.types import analyze_program_result
    from sd_core.tooling.harness import ProgramResult

    sources = _load_case_sources(case)
    program = ProgramResult.from_sources(sources)
    edges: set[Edge] = set()
    program_run = analyze_program_result(
        program,
        body_summary_consumption="safe",
        analysis_product=analysis_product,
        external_from_import_fallback=True,
        callable_root_activation=callable_root_activation,
        callable_root_body_ids=callable_root_body_ids,
    )
    structural_runs = {
        module_name: analyze_morphism(
            translation.morphism,
            registry=program_run.modules[module_name].target.registry,
        )
        for module_name, translation in sorted(program.modules.items())
        if module_name in program_run.modules
        and program_run.modules[module_name].target.registry is not None
    }
    function_names: dict[str, str] = {}
    for module_name, structural in structural_runs.items():
        type_run = program_run.modules[module_name]
        function_names.update(
            _function_display_names(module_name, structural.functions, type_run.target)
        )

    for module_name, structural in sorted(structural_runs.items()):
        type_run = program_run.modules.get(module_name)
        if type_run is None:
            continue
        registry = type_run.target.registry
        if registry is None:
            continue
        projection = project_call_relation(
            structural,
            seed_id=f"sid:v1:pycg-seed:{case.suite_path}:{module_name}",
            context_id=f"sid:v1:pycg-context:{case.suite_path}:module-load",
            registry=registry,
        )
        for edge in projection.edges:
            if edge.precision in {"name_hint", "unresolved"}:
                if not include_diagnostic_name_hints:
                    continue
                caller = (
                    module_name
                    if edge.caller_body_id is None
                    else function_names.get(edge.caller_body_id)
                )
                if caller is None:
                    continue
                for callee_id in edge.callee_body_ids:
                    callee = function_names.get(callee_id)
                    if callee is not None:
                        edges.add((caller, callee))
                continue
            caller = (
                module_name
                if edge.caller_body_id is None
                else function_names.get(edge.caller_body_id)
            )
            if caller is None:
                continue
            for callee_id in edge.callee_body_ids:
                callee = _callee_display_name(callee_id, function_names)
                if callee is not None:
                    edges.add((caller, callee))
    return _inline_synthetic_frame_edges(edges)


def _load_case_sources(case: PyCGCase) -> dict[str, str]:
    sources: dict[str, str] = {}
    for path in case.source_paths:
        module_name = _module_name_for_path(path, case.package_root)
        source = path.read_text(encoding="utf-8-sig")
        if path.name == "__init__.py" and not source.strip():
            source = "pass\n"
        sources[module_name] = source
    return sources


def _module_name_for_path(path: Path, package_root: Path) -> str:
    rel = path.relative_to(package_root)
    parts = list(rel.parent.parts) if rel.parent != Path(".") else []
    if rel.stem != "__init__":
        parts.append(rel.stem)
    elif not parts:
        parts.append(package_root.name)
    return ".".join(parts)


_SYNTHETIC_FRAME_NAMES = frozenset(
    {
        "<listcomp>",
        "<dictcomp>",
        "<setcomp>",
        "<genexpr>",
    }
)


def _inline_synthetic_frame_edges(
    edges: Iterable[tuple[str, str]],
) -> set[tuple[str, str]]:
    """Project compiler-generated expression frames onto source callers.

    Archway's semantic call relation exposes implementation frames such as
    ``main.<listcomp>`` because those frames exist in the translated IR. PyCG's
    source-call graph format attributes calls inside comprehensions to the
    enclosing source scope. This post-process is intentionally display-only: it
    rewrites existing edges through synthetic frames and does not create targets
    that were not present in the semantic readout.
    """

    projected, _lineage = _inline_synthetic_frame_edges_with_evidence(edges)
    return projected


def _inline_synthetic_frame_edges_with_evidence(
    edges: Iterable[tuple[str, str]],
) -> tuple[set[tuple[str, str]], tuple[dict[str, object], ...]]:
    """Return the PyCG display projection and explicit edge lineage."""

    edge_set = set(edges)
    synthetic_parents: dict[str, set[str]] = {}
    for caller, callee in edge_set:
        if _is_synthetic_frame(callee):
            synthetic_parents.setdefault(callee, set()).add(caller)

    def source_parents(frame: str, seen: frozenset[str] = frozenset()) -> set[str]:
        if frame in seen:
            return set()
        parents = synthetic_parents.get(frame, set())
        if not parents:
            return set()
        resolved: set[str] = set()
        for parent in parents:
            if _is_synthetic_frame(parent):
                resolved.update(source_parents(parent, seen | {frame}))
            else:
                resolved.add(parent)
        return resolved

    projected: set[tuple[str, str]] = set()
    lineage: list[dict[str, object]] = []
    for caller, callee in edge_set:
        caller_is_synthetic = _is_synthetic_frame(caller)
        callee_is_synthetic = _is_synthetic_frame(callee)
        if callee_is_synthetic or _is_synthetic_implementation_target(callee):
            lineage.append({
                "action": "omit_synthetic_target",
                "input_edge": [caller, callee],
                "output_edge": None,
            })
            continue
        if caller_is_synthetic:
            for parent in source_parents(caller):
                projected.add((parent, callee))
                lineage.append({
                    "action": "attribute_synthetic_caller",
                    "input_edge": [caller, callee],
                    "output_edge": [parent, callee],
                    "synthetic_caller": caller,
                })
            continue
        projected.add((caller, callee))
        lineage.append({
            "action": "retain",
            "input_edge": [caller, callee],
            "output_edge": [caller, callee],
        })
    return projected, tuple(sorted(
        lineage,
        key=lambda item: (
            str(item["action"]),
            tuple(item["input_edge"]),
            tuple(item["output_edge"] or ()),
        ),
    ))


def _is_synthetic_frame(name: str) -> bool:
    return _last_qualified_part(name) in _SYNTHETIC_FRAME_NAMES


def _last_qualified_part(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _is_synthetic_implementation_target(name: str) -> bool:
    return name in {
        "<builtin>.iter",
        "<builtin-method>.list.append",
        "<builtin-method>.set.add",
        "<builtin-method>.dict.__setitem__",
        "<**PyDict**>.update",
        "<builtin>.staticmethod",
    }


def _successor_pycg_target_name(name: str) -> str:
    """Translate semantic boundary names into PyCG's display vocabulary."""

    for semantic, pycg in (
        ("<builtin>.str.", "<**PyStr**>."),
        ("<builtin>.dict.", "<**PyDict**>."),
        ("<builtin>.list.", "<**PyList**>."),
        ("<builtin>.set.", "<**PySet**>."),
        ("<builtin>.file.", "<**PyFile**>."),
    ):
        if name.startswith(semantic):
            return pycg + name.removeprefix(semantic)
    return name


def _callee_display_name(
    callee_id: str,
    function_names: Mapping[str, str],
) -> str | None:
    if callee_id.startswith("sid:v1:external-dependency-call:"):
        return callee_id.removeprefix("sid:v1:external-dependency-call:")
    if callee_id.startswith("sid:v1:builtin:"):
        return f"<builtin>.{callee_id.removeprefix('sid:v1:builtin:')}"
    if callee_id.startswith("sid:v1:builtin-method:"):
        rest = callee_id.removeprefix("sid:v1:builtin-method:")
        receiver, _, method = rest.partition(":")
        pycg_receiver = {
            "dict": "<**PyDict**>",
            "str": "<**PyStr**>",
        }.get(receiver)
        if pycg_receiver is None:
            return f"<builtin-method>.{receiver}.{method}"
        return f"{pycg_receiver}.{method}"
    if callee_id.startswith("sid:v1:external-dependency-call:"):
        return callee_id.removeprefix("sid:v1:external-dependency-call:")
    return function_names.get(callee_id)


def _method_owner_name(target: object, body_id: str) -> str | None:
    owners = getattr(target, "method_owners", {})
    owner = owners.get(body_id) if isinstance(owners, dict) else None
    name = getattr(owner, "name", None)
    return name if isinstance(name, str) and name else None


def _function_display_names(
    module_name: str,
    functions: Iterable[object],
    target: object,
) -> dict[str, str]:
    by_id = {
        getattr(function, "body_id"): function
        for function in functions
        if isinstance(getattr(function, "body_id", None), str)
    }
    lambda_names: dict[str, str] = {}
    lambda_index = 0
    for function in functions:
        body_id = getattr(function, "body_id", None)
        if not isinstance(body_id, str):
            continue
        if getattr(function, "name", None) == "<lambda>":
            lambda_index += 1
            lambda_names[body_id] = f"<lambda{lambda_index}>"

    resolved: dict[str, str] = {}
    resolving: set[str] = set()

    def resolve(body_id: str) -> str | None:
        if body_id in resolved:
            return resolved[body_id]
        if body_id in resolving:
            return None
        function = by_id.get(body_id)
        if function is None:
            return None
        resolving.add(body_id)
        raw_name = getattr(function, "name", None)
        if not isinstance(raw_name, str) or not raw_name:
            resolving.remove(body_id)
            return None
        function_name = lambda_names.get(body_id, raw_name)
        lexical_parent = getattr(function, "lexical_parent_body_id", None)
        parent_name = (
            resolve(lexical_parent)
            if isinstance(lexical_parent, str)
            else None
        )
        if parent_name is not None:
            display = f"{parent_name}.{function_name}"
        else:
            display = _qualify_function_name(
                module_name,
                function_name,
                owner_name=_method_owner_name(target, body_id),
            )
        resolving.remove(body_id)
        resolved[body_id] = display
        return display

    for body_id in by_id:
        resolve(body_id)
    return resolved


def _qualify_function_name(
    module_name: str,
    function_name: str,
    *,
    owner_name: str | None = None,
) -> str:
    if function_name.startswith(module_name + "."):
        return function_name
    if owner_name is not None:
        owner = owner_name
        if owner.startswith(module_name + "."):
            owner = owner.removeprefix(module_name + ".")
        return f"{module_name}.{owner}.{function_name}"
    return f"{module_name}.{function_name}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m archway_benchmarks.pycg")
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--engine-root", required=True)
    parser.add_argument("--suite", choices=("micro", "macro"), default="micro")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Run one named case. Repeat to select multiple cases.",
    )
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--case-timeout-seconds",
        type=float,
        default=None,
        help=(
            "Optional per-case wall-clock timeout. Timed-out cases are recorded "
            "with status=timeout and zero predicted edges; the run continues."
        ),
    )
    parser.add_argument(
        "--edge-provider",
        choices=("successor", "coordinated", "legacy"),
        default="successor",
        help=(
            "Call-edge producer. successor uses the diagram-only fact runtime; "
            "coordinated is the quarantined source-index runtime; legacy "
            "projects the reduced-product call relation."
        ),
    )
    parser.add_argument(
        "--analysis-product",
        choices=("standalone", "type_requirements_product"),
        default="standalone",
        help=(
            "Archway program analysis product mode. The default preserves the "
            "legacy program-level type runner; type_requirements_product runs "
            "the fuller reduced-product participant path."
        ),
    )
    parser.add_argument(
        "--callable-root-activation",
        choices=("off", "all"),
        default="off",
        help=(
            "Opt-in engine root policy. 'all' analyzes every uncalled "
            "parameter-bearing source callable with conservative arguments."
        ),
    )
    parser.add_argument(
        "--include-diagnostic-name-hints",
        action="store_true",
        help=(
            "Include structural name-hint edges. These are diagnostic only and "
            "must not be treated as claim-grade semantic call targets."
        ),
    )
    parser.add_argument(
        "--successor-record-events",
        action="store_true",
        help=(
            "Retain detailed successor scheduler/transfer events. Facts and "
            "knowledge deltas remain measured when this is disabled."
        ),
    )
    parser.add_argument(
        "--successor-summarize-callee-results",
        action="store_true",
        help=(
            "Use shared compositional callable summaries for callees reached "
            "from whole-program callable roots."
        ),
    )
    parser.add_argument(
        "--successor-sampling-rate-hz",
        type=float,
        default=None,
        help=(
            "Collect a low-overhead aggregate Python stack sample profile at "
            "the requested frequency. Disabled by default."
        ),
    )
    parser.add_argument(
        "--successor-partial-graph-checkpoint-seconds",
        type=float,
        default=None,
        help=(
            "Periodically project and score a non-converged semantic graph "
            "during timeout-isolated successor runs. Disabled by default "
            "because projection has measurable cost."
        ),
    )
    args = parser.parse_args(argv)

    result = run_archway_pycg(
        corpus_root=Path(args.corpus_root),
        engine_root=Path(args.engine_root),
        suite=args.suite,
        limit=args.limit,
        case_names=tuple(args.case),
        include_diagnostic_name_hints=args.include_diagnostic_name_hints,
        analysis_product=args.analysis_product,
        callable_root_activation=args.callable_root_activation,
        case_timeout_seconds=args.case_timeout_seconds,
        edge_provider=args.edge_provider,
        successor_record_events=args.successor_record_events,
        successor_summarize_callee_results=(
            args.successor_summarize_callee_results
        ),
        successor_sampling_rate_hz=args.successor_sampling_rate_hz,
        successor_partial_graph_checkpoint_seconds=(
            args.successor_partial_graph_checkpoint_seconds
        ),
    )
    payload = result.to_jsonable()
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        _write_json_artifact(Path(args.output), text)
    else:
        print(text)
    print(
        f"PyCG Archway {result.suite} score: "
        f"precision={result.score.precision:.3f} "
        f"recall={result.score.recall:.3f} "
        f"f1={result.score.f1:.3f} "
        f"edges={result.score.true_positive}/"
        f"{result.expected_edges_total}",
        file=sys.stderr,
    )
    return 0


def _write_json_artifact(path: Path, text: str) -> None:
    """Persist an explicitly requested result, including its storage namespace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
