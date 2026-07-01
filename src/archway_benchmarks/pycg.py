"""PyCG micro-benchmark loader, scorer, and Archway runner.

This module targets PyCG's published micro benchmark shape:

```
micro-benchmark/snippets/<category>/<case>/main.py
micro-benchmark/snippets/<category>/<case>/callgraph.json
```

The scorer is intentionally graph-shaped rather than annotation-shaped. It
reports edge precision/recall/F1 with explicit case and edge denominators.
Archway predictions are produced from Archway call-relation surfaces when
available; structural name hints remain diagnostic and are not claim-grade
semantic call targets.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

Edge = tuple[str, str]


@dataclass(frozen=True)
class PyCGCase:
    suite_path: str
    root: Path
    main_path: Path
    expected: dict[str, tuple[str, ...]]

    @property
    def expected_edges(self) -> frozenset[Edge]:
        return frozenset(expected_edges_from_callgraph(self.expected))


@dataclass(frozen=True)
class EdgeScore:
    true_positive: int
    false_positive: int
    false_negative: int

    @property
    def precision(self) -> float:
        denom = self.true_positive + self.false_positive
        return self.true_positive / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positive + self.false_negative
        return self.true_positive / denom if denom else 0.0

    @property
    def f1(self) -> float:
        denom = self.precision + self.recall
        return 2 * self.precision * self.recall / denom if denom else 0.0

    def to_jsonable(self) -> dict[str, float | int]:
        return {
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


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
        }


@dataclass(frozen=True)
class PyCGRunResult:
    corpus_root: str
    engine_root: str
    cases_total: int
    cases_attempted: int
    cases_ok: int
    cases_error: int
    expected_edges_total: int
    predicted_edges_total: int
    score: EdgeScore
    elapsed_seconds: float
    cases: tuple[PyCGCaseResult, ...] = field(default_factory=tuple)

    def to_jsonable(self) -> dict:
        return {
            "corpus_root": self.corpus_root,
            "engine_root": self.engine_root,
            "cases_total": self.cases_total,
            "cases_attempted": self.cases_attempted,
            "cases_ok": self.cases_ok,
            "cases_error": self.cases_error,
            "expected_edges_total": self.expected_edges_total,
            "predicted_edges_total": self.predicted_edges_total,
            "score": self.score.to_jsonable(),
            "elapsed_seconds": self.elapsed_seconds,
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


def load_cases(corpus_root: Path, *, limit: int | None = None) -> tuple[PyCGCase, ...]:
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
                suite_path=str(case_root.relative_to(snippet_root)),
                root=case_root,
                main_path=main_path,
                expected=expected,
            )
        )
        if limit is not None and len(cases) >= limit:
            break
    return tuple(cases)


def run_archway_pycg(
    *,
    corpus_root: Path,
    engine_root: Path,
    limit: int | None = None,
    include_diagnostic_name_hints: bool = False,
    analysis_product: str = "standalone",
) -> PyCGRunResult:
    cases = load_cases(corpus_root, limit=limit)
    started = time.perf_counter()
    results: list[PyCGCaseResult] = []
    total = EdgeScore(0, 0, 0)
    predicted_total = 0
    expected_total = 0

    for case in cases:
        case_started = time.perf_counter()
        expected = set(case.expected_edges)
        expected_total += len(expected)
        try:
            predicted = archway_call_edges(
                case,
                engine_root=engine_root,
                include_diagnostic_name_hints=include_diagnostic_name_hints,
                analysis_product=analysis_product,
            )
            status = "ok"
            error = None
        except Exception as exc:
            predicted = set()
            status = "error"
            error = f"{type(exc).__name__}: {exc}"
        score = score_edges(expected, predicted)
        total = EdgeScore(
            total.true_positive + score.true_positive,
            total.false_positive + score.false_positive,
            total.false_negative + score.false_negative,
        )
        predicted_total += len(predicted)
        results.append(
            PyCGCaseResult(
                suite_path=case.suite_path,
                expected_edge_count=len(expected),
                predicted_edge_count=len(predicted),
                score=score,
                status=status,
                error=error,
                elapsed_seconds=time.perf_counter() - case_started,
                predicted_edges=tuple(sorted(predicted)),
                missing_edges=tuple(sorted(expected - predicted)),
                extra_edges=tuple(sorted(predicted - expected)),
            )
        )

    return PyCGRunResult(
        corpus_root=str(corpus_root),
        engine_root=str(engine_root),
        cases_total=len(cases),
        cases_attempted=len(cases),
        cases_ok=sum(1 for result in results if result.status == "ok"),
        cases_error=sum(1 for result in results if result.status != "ok"),
        expected_edges_total=expected_total,
        predicted_edges_total=predicted_total,
        score=total,
        elapsed_seconds=time.perf_counter() - started,
        cases=tuple(results),
    )


def archway_call_edges(
    case: PyCGCase,
    *,
    engine_root: Path,
    include_diagnostic_name_hints: bool = False,
    analysis_product: str = "standalone",
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
    from sd_core.analysis.types.runner import load_package
    from sd_core.runners.types import analyze_program_result
    from sd_core.tooling.harness import ProgramResult

    sources = load_package(case.root)
    program = ProgramResult.from_sources(sources)
    edges: set[Edge] = set()
    program_run = analyze_program_result(
        program,
        body_summary_consumption="safe",
        analysis_product=analysis_product,
        external_from_import_fallback=True,
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
    for caller, callee in edge_set:
        caller_is_synthetic = _is_synthetic_frame(caller)
        callee_is_synthetic = _is_synthetic_frame(callee)
        if callee_is_synthetic or _is_synthetic_implementation_target(callee):
            continue
        if caller_is_synthetic:
            for parent in source_parents(caller):
                projected.add((parent, callee))
            continue
        projected.add((caller, callee))
    return projected


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
    }


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
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", default=None)
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
        "--include-diagnostic-name-hints",
        action="store_true",
        help=(
            "Include structural name-hint edges. These are diagnostic only and "
            "must not be treated as claim-grade semantic call targets."
        ),
    )
    args = parser.parse_args(argv)

    result = run_archway_pycg(
        corpus_root=Path(args.corpus_root),
        engine_root=Path(args.engine_root),
        limit=args.limit,
        include_diagnostic_name_hints=args.include_diagnostic_name_hints,
        analysis_product=args.analysis_product,
    )
    payload = result.to_jsonable()
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    print(
        "PyCG Archway score: "
        f"precision={result.score.precision:.3f} "
        f"recall={result.score.recall:.3f} "
        f"f1={result.score.f1:.3f} "
        f"edges={result.score.true_positive}/"
        f"{result.expected_edges_total}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
