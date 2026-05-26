"""Corpus manifest — the source of truth for dashboard slicing and worklists.

Generates `corpus_manifest.json` by scanning the TypeEvalPy corpus:

  - per-snippet: category, path, loc, annotation_count, FR/FP/LV counts,
    AST-detected feature set, import profile, payoff-curve flags
  - per-annotation: kind, category, is_function_parameter, is_callable_gt

Regenerate with:  `archway-bench manifest` (or `python -m archway_benchmarks.manifest`).
"""
from __future__ import annotations

import ast
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from archway_benchmarks.benchmarks.typeevalpy import TypeEvalPyBenchmark

# Feature set the manifest exposes for filtering / payoff curves.
FEATURE_NAMES = (
    "class",
    "lambda",
    "comprehension",
    "decorator",
    "yield",
    "loop",
    "try",
    "import",
    "default_args",
    "kwargs",
)

# Features whose absence defines the "minimal floor" payoff slice (none of these).
_MINIMAL_FLOOR_EXCLUDED = (
    "class",
    "lambda",
    "comprehension",
    "decorator",
    "yield",
    "try",
    "import",
)
# Features still excluded once `class` is allowed in (minimal + class only).
_CLASSES_SLICE_EXCLUDED = tuple(f for f in _MINIMAL_FLOOR_EXCLUDED if f != "class")

# Standard-library top-level packages we treat as `stdlib`. Anything else with
# `import x` resolves to either `local_fixture` (a sibling .py exists) or
# `external_lib`.
_STDLIB_TOPLEVELS = frozenset(
    {
        "abc", "argparse", "asyncio", "base64", "binascii", "builtins",
        "collections", "concurrent", "contextlib", "copy", "csv", "ctypes",
        "dataclasses", "datetime", "decimal", "enum", "errno", "fnmatch",
        "functools", "gc", "glob", "hashlib", "heapq", "hmac", "html", "http",
        "importlib", "inspect", "io", "ipaddress", "itertools", "json",
        "logging", "math", "multiprocessing", "operator", "os", "pathlib",
        "pickle", "queue", "random", "re", "shutil", "signal", "socket",
        "sqlite3", "statistics", "string", "struct", "subprocess", "sys",
        "tempfile", "textwrap", "threading", "time", "timeit", "tokenize",
        "traceback", "types", "typing", "unicodedata", "unittest", "urllib",
        "uuid", "warnings", "weakref", "xml", "zipfile",
    }
)


@dataclass(frozen=True)
class AnnotationRecord:
    location_file: str
    line: int
    col: int
    kind: str  # "return" | "parameter" | "variable"
    name: str
    function: str | None
    category: str
    types: list[str]
    is_function_parameter: bool
    is_callable_gt: bool


@dataclass(frozen=True)
class SnippetRecord:
    category: str
    path: str
    loc: int
    annotation_count: int
    kind_counts: dict[str, int]  # {"return": N, "parameter": N, "variable": N}
    features: list[str]
    import_profile: str  # "none" | "stdlib" | "local_fixture" | "external_lib"
    in_minimal_floor: bool
    in_classes_slice: bool
    in_no_imports_slice: bool
    annotations: list[AnnotationRecord]


@dataclass
class Manifest:
    benchmark: str
    total_snippets: int
    total_annotations: int
    snippets: list[SnippetRecord] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        s = self.snippets
        total_ann = self.total_annotations
        floor = [x for x in s if x.in_minimal_floor]
        classes = [x for x in s if x.in_classes_slice]
        no_imports = [x for x in s if x.in_no_imports_slice]
        floor_ann = sum(x.annotation_count for x in floor)
        classes_ann = sum(x.annotation_count for x in classes)
        no_imports_ann = sum(x.annotation_count for x in no_imports)
        fp = sum(1 for x in s for a in x.annotations if a.is_function_parameter)
        callable_gt = sum(1 for x in s for a in x.annotations if a.is_callable_gt)
        return {
            "total_snippets": len(s),
            "total_annotations": total_ann,
            "minimal_floor_snippets": len(floor),
            "minimal_floor_annotations": floor_ann,
            "minimal_floor_pct": round(floor_ann / total_ann * 100, 1),
            "classes_slice_snippets": len(classes),
            "classes_slice_annotations": classes_ann,
            "classes_slice_pct": round(classes_ann / total_ann * 100, 1),
            "no_imports_slice_snippets": len(no_imports),
            "no_imports_slice_annotations": no_imports_ann,
            "no_imports_slice_pct": round(no_imports_ann / total_ann * 100, 1),
            "function_parameter_annotations": fp,
            "callable_gt_annotations": callable_gt,
        }


def generate(benchmark: TypeEvalPyBenchmark | None = None) -> Manifest:
    bench = benchmark or TypeEvalPyBenchmark()
    snippets = bench.load()

    manifest = Manifest(
        benchmark=bench.name,
        total_snippets=len(snippets),
        total_annotations=sum(len(s.annotations) for s in snippets),
    )

    for snip in snippets:
        category = snip.suite_path.split("/", 1)[0]
        source = snip.source
        try:
            tree = ast.parse(source)
        except SyntaxError:
            tree = None

        features = _detect_features(tree) if tree else set()
        import_profile = _detect_import_profile(tree, snip.suite_path, bench.corpus_root)
        loc = source.count("\n") + (0 if source.endswith("\n") else 1)
        kind_counts = {"return": 0, "parameter": 0, "variable": 0}
        for a in snip.annotations:
            kind_counts[a.location.kind] += 1

        in_minimal_floor = not (features & set(_MINIMAL_FLOOR_EXCLUDED))
        in_classes_slice = not (features & set(_CLASSES_SLICE_EXCLUDED))
        in_no_imports_slice = "import" not in features

        ann_records = [
            AnnotationRecord(
                location_file=a.location.file,
                line=a.location.line,
                col=a.location.col or 0,
                kind=a.location.kind,
                name=a.location.name,
                function=a.location.function,
                category=category,
                types=sorted(a.types),
                is_function_parameter=(a.location.kind == "parameter"),
                is_callable_gt=(a.types == frozenset({"callable"})),
            )
            for a in snip.annotations
        ]

        manifest.snippets.append(
            SnippetRecord(
                category=category,
                path=snip.suite_path,
                loc=loc,
                annotation_count=len(snip.annotations),
                kind_counts=kind_counts,
                features=sorted(features),
                import_profile=import_profile,
                in_minimal_floor=in_minimal_floor,
                in_classes_slice=in_classes_slice,
                in_no_imports_slice=in_no_imports_slice,
                annotations=ann_records,
            )
        )

    return manifest


def write(manifest: Manifest, path: Path) -> None:
    payload = {
        "benchmark": manifest.benchmark,
        "total_snippets": manifest.total_snippets,
        "total_annotations": manifest.total_annotations,
        "summary": manifest.summary(),
        "snippets": [asdict(s) for s in manifest.snippets],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")


# ----- AST feature detection -----

def _detect_features(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            found.add("class")
        elif isinstance(node, ast.Lambda):
            found.add("lambda")
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            found.add("comprehension")
        elif isinstance(node, (ast.For, ast.While, ast.AsyncFor)):
            found.add("loop")
        elif isinstance(node, (ast.Try,)):
            found.add("try")
        elif isinstance(node, (ast.Yield, ast.YieldFrom)):
            found.add("yield")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            found.add("import")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.decorator_list:
                found.add("decorator")
            if node.args.defaults or node.args.kw_defaults:
                found.add("default_args")
            if node.args.kwarg is not None or node.args.kwonlyargs:
                found.add("kwargs")
        elif isinstance(node, ast.ClassDef):
            if node.decorator_list:
                found.add("decorator")
    return found


def _detect_import_profile(
    tree: ast.AST | None, suite_path: str, corpus_root: Path
) -> str:
    if tree is None:
        return "none"

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # relative — local fixture import (e.g. `from .helper import x`)
                imports.append("__relative__")
            elif node.module:
                imports.append(node.module.split(".")[0])

    if not imports:
        return "none"

    snippet_dir = corpus_root / suite_path
    profiles: set[str] = set()
    for name in imports:
        if name == "__relative__":
            profiles.add("local_fixture")
        elif name in _STDLIB_TOPLEVELS:
            profiles.add("stdlib")
        elif (snippet_dir / f"{name}.py").exists() or (snippet_dir / name).is_dir():
            profiles.add("local_fixture")
        else:
            profiles.add("external_lib")

    # Most-specific wins: external_lib > local_fixture > stdlib > none
    for level in ("external_lib", "local_fixture", "stdlib"):
        if level in profiles:
            return level
    return "none"


def _cli(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="archway-bench-manifest")
    parser.add_argument(
        "--output",
        "-o",
        default="corpus_manifest.json",
        help="Output path (default: corpus_manifest.json in cwd)",
    )
    parser.add_argument(
        "--corpus",
        default=None,
        help="Override the corpus root (defaults to vendor/TypeEvalPy/micro-benchmark/python_features)",
    )
    args = parser.parse_args(argv)

    bench = TypeEvalPyBenchmark(corpus_root=Path(args.corpus) if args.corpus else None)
    manifest = generate(bench)
    out_path = Path(args.output)
    write(manifest, out_path)

    summary = manifest.summary()
    print(f"Wrote {out_path}")
    print(f"  {summary['total_snippets']} snippets, {summary['total_annotations']} annotations")
    print(
        f"  minimal floor: {summary['minimal_floor_snippets']} snippets, "
        f"{summary['minimal_floor_annotations']} anns ({summary['minimal_floor_pct']}%)"
    )
    print(
        f"  +classes:      {summary['classes_slice_snippets']} snippets, "
        f"{summary['classes_slice_annotations']} anns ({summary['classes_slice_pct']}%)"
    )
    print(
        f"  no imports:    {summary['no_imports_slice_snippets']} snippets, "
        f"{summary['no_imports_slice_annotations']} anns ({summary['no_imports_slice_pct']}%)"
    )
    print(f"  function parameters: {summary['function_parameter_annotations']} anns")
    print(f"  callable GT:         {summary['callable_gt_annotations']} anns")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
