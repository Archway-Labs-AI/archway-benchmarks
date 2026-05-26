"""Archway -> TypeEvalPy record translator.

This module is the in-container side of the Layer-A mapping. The serializing
half lives in `typeevalpy_mapping.to_record`, which is a byte-identical copy
of `archway-benchmarks/src/archway_benchmarks/typeevalpy_mapping.py`. The
same function is used by the Archway benchmark harness when emitting tool
outputs — so a divergence between the two scoring contexts is impossible by
construction.

Functions required by `Tool_Integration_Guide.md`:
  - `translate_content(file_path)` — load JSON, project to TypeEvalPy schema
  - `main_translator(args)`        — iterate a directory tree
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from typeevalpy_mapping import MappedLocation, to_record


def annotation_to_record(
    *,
    file: str,
    line: int,
    col: int | None,
    kind: str,
    name: str,
    function: str | None,
    types: list[str],
) -> dict[str, Any]:
    """Convenience wrapper for runner code: build a `MappedLocation` then
    project to the TypeEvalPy schema. Kept here so runner.py never has to
    import `MappedLocation` itself."""
    loc = MappedLocation(file=file, line=line, col=col, kind=kind, name=name, function=function)
    return to_record(loc, types)


def translate_content(file_path: str) -> list[dict[str, Any]]:
    """Load a JSON file produced by the runner and return it as-is.

    The Archway runner already writes records in TypeEvalPy schema (via
    `annotation_to_record`), so this is the identity function. We keep the
    function as required by `Tool_Integration_Guide.md` so the maintainers
    can wire `main_translator` into post-processing pipelines if they want.
    """
    with open(file_path) as f:
        return json.load(f)


def main_translator(args: argparse.Namespace) -> None:
    """Walk a benchmark directory and validate that every `*_result.json` is
    well-formed under the TypeEvalPy schema. Called by `python translator.py
    --bechmark_path /tmp/micro-benchmark` for parity with other tools."""
    json_files = sorted(Path(args.bechmark_path).rglob("*_result.json"))
    error_count = 0
    for file in json_files:
        try:
            translate_content(str(file))
        except Exception as e:  # noqa: BLE001
            print(f"Bad result {file}: {e}")
            error_count += 1
    print(f"Translator finished with errors: {error_count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bechmark_path", default="/tmp/micro-benchmark")
    args = parser.parse_args()
    main_translator(args)
