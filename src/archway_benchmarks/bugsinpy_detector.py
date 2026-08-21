"""Ground-truth-blind BugsInPy detector backed by Archway analysis evidence."""

from __future__ import annotations

import argparse
import ast
import json
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from archway_benchmarks.bugsinpy_protocol import (
    DetectorInputManifest,
    RankedFinding,
    RankedPredictionBundle,
)


_IGNORED_DIRECTORIES = frozenset(
    {".git", ".hg", ".mypy_cache", ".pytest_cache", ".tox", ".venv", "build", "dist", "venv"}
)
_FILE_TIMEOUT_SECONDS = 10


@dataclass(frozen=True, slots=True)
class ExceptionFindingEvidence:
    file: str
    start_line: int
    end_line: int
    classes: tuple[str, ...]
    provenance: str


def detect(manifest: DetectorInputManifest) -> RankedPredictionBundle:
    """Analyze every Python source visible in the sanitized checkout."""

    root = Path(manifest.repository_root).resolve()
    sources = tuple(_python_sources(root))
    repository_loc = sum(_line_count(path) for path in sources)
    analyzed_files = 0
    analyzed_loc = 0
    evidence: list[ExceptionFindingEvidence] = []
    for path in sources:
        relative = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            candidates = _analyze_file_with_timeout(source, relative)
        except Exception:
            # Coverage makes translation/analysis failures visible in scoring.
            continue
        analyzed_files += 1
        analyzed_loc += _source_line_count(source)
        evidence.extend(candidates)

    ordered = sorted(
        evidence,
        key=lambda item: (
            _exception_priority(item.classes),
            item.file,
            item.start_line,
            item.end_line,
            item.provenance,
        ),
    )
    findings = tuple(
        RankedFinding(
            rank=index,
            file=item.file,
            start_line=item.start_line,
            end_line=item.end_line,
            kind="definite-runtime-exception",
            confidence=1.0,
            evidence=(
                {
                    "engine": "archway-combined-exception-effects",
                    "origin": "semantic_runtime",
                    "must_raise": True,
                    "exception_classes": list(item.classes),
                    "provenance": item.provenance,
                },
            ),
            reachability={"status": "not-proven-unreachable"},
        )
        for index, item in enumerate(_deduplicate(ordered), start=1)
    )
    return RankedPredictionBundle(
        protocol=manifest.protocol,
        bug_key=manifest.bug_key,
        buggy_revision=manifest.buggy_revision,
        findings=findings,
        repository_files=len(sources),
        repository_loc=repository_loc,
        analyzed_files=analyzed_files,
        analyzed_loc=analyzed_loc,
    )


def _analyze_file(source: str, relative_path: str) -> tuple[ExceptionFindingEvidence, ...]:
    """Run Archway lazily so importing the public protocol needs no engine install."""

    from sd_core.analysis.base import core_access as ca
    from sd_core.runners.program import analyze_source

    tree = ast.parse(source, filename=relative_path)
    run = analyze_source(source, name=_module_name(relative_path))
    findings: list[ExceptionFindingEvidence] = []
    for box, effect in run.exceptions.effects:
        if effect.origin != "semantic_runtime" or not effect.must_raise:
            continue
        # Read translation provenance directly from the effect-owning box.
        # Importing the successor catalog here would unnecessarily make this
        # reduced-product detector depend on the successor runtime package.
        wires = tuple(ca.box_output_leaves(box)) or tuple(ca.box_argument_leaves(box))
        positions = tuple(
            position for wire in wires
            if (position := ca.wire_source_position(wire)) is not None
        )
        position = min(
            positions,
            key=lambda item: (item.row, item.col, item.end_row, item.end_col),
        ) if positions else None
        if position is None or position.row < 1:
            continue
        classes = tuple(sorted(effect.classes))
        if _guarded_by_enclosing_try(tree, position.row) or _import_statement_at(tree, position.row):
            continue
        findings.append(
            ExceptionFindingEvidence(
                file=relative_path,
                start_line=position.row,
                end_line=max(position.row, position.end_row),
                classes=classes,
                provenance=effect.provenance or "",
            )
        )
    return tuple(findings)


def _analyze_file_with_timeout(
    source: str, relative_path: str
) -> tuple[ExceptionFindingEvidence, ...]:
    """Bound known translation/analysis nontermination on POSIX runners."""

    if not hasattr(signal, "SIGALRM"):
        return _analyze_file(source, relative_path)

    def expired(_signum, _frame):
        raise TimeoutError(f"Archway analysis exceeded {_FILE_TIMEOUT_SECONDS}s")

    previous_handler = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, _FILE_TIMEOUT_SECONDS)
    try:
        return _analyze_file(source, relative_path)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _guarded_by_enclosing_try(tree: ast.AST, line: int) -> bool:
    """Suppress protected operations; handler matching is not yet claim-grade."""

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Try, ast.TryStar)) or not node.body:
            continue
        start = min(item.lineno for item in node.body)
        end = max(getattr(item, "end_lineno", item.lineno) for item in node.body)
        if start <= line <= end:
            return True
    return False


def _import_statement_at(tree: ast.AST, line: int) -> bool:
    return any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and node.lineno <= line <= getattr(node, "end_lineno", node.lineno)
        for node in ast.walk(tree)
    )


def _python_sources(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        relative_parts = path.relative_to(root).parts
        if not any(part in _IGNORED_DIRECTORIES for part in relative_parts) and path.is_file():
            yield path


def _module_name(relative_path: str) -> str:
    parts = list(Path(relative_path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(part.replace("-", "_") for part in parts) or "main"


def _source_line_count(source: str) -> int:
    return len(source.splitlines())


def _line_count(path: Path) -> int:
    return _source_line_count(path.read_text(encoding="utf-8", errors="replace"))


def _exception_priority(classes: tuple[str, ...]) -> tuple[int, tuple[str, ...]]:
    order = {"ZeroDivisionError": 0, "TypeError": 1, "AttributeError": 2, "KeyError": 3}
    return (min((order.get(item, 10) for item in classes), default=10), classes)


def _deduplicate(items: Iterable[ExceptionFindingEvidence]) -> Iterable[ExceptionFindingEvidence]:
    seen: set[tuple[str, int, int]] = set()
    for item in items:
        key = (item.file, item.start_line, item.end_line)
        if key not in seen:
            seen.add(key)
            yield item


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    manifest = DetectorInputManifest.from_json(json.loads(args.manifest.read_text()))
    prediction = detect(manifest)
    args.output.write_text(json.dumps(prediction.to_json(), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
