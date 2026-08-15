from __future__ import annotations

import importlib.util
from pathlib import Path


_PATH = Path(__file__).parents[1] / "scripts" / "typybench_successor_run.py"
_SPEC = importlib.util.spec_from_file_location("typybench_successor_run", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_terminal_status_requires_every_repository_to_complete() -> None:
    assert _MODULE._terminal_run_status(
        {"a": {"status": "complete"}, "b": {"status": "complete"}},
        ["a", "b"],
    ) == "complete"
    assert _MODULE._terminal_run_status(
        {"a": {"status": "complete"}, "b": {"status": "failed"}},
        ["a", "b"],
    ) == "finished_with_incomplete_repositories"
    assert _MODULE._terminal_run_status(
        {"a": {"status": "complete"}}, ["a", "b"]
    ) == "finished_with_incomplete_repositories"


def test_terminal_status_discloses_interrupted_running_record() -> None:
    assert _MODULE._terminal_run_status(
        {"a": {"status": "running"}}, ["a"]
    ) == "interrupted"
