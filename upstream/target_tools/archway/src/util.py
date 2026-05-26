"""Utility helpers — kept minimal and matching the docker_template's util.py."""
from __future__ import annotations

import os


def is_running_in_docker() -> bool:
    """Heuristics matching the rest of TypeEvalPy's tools."""
    return (
        os.path.exists("/.dockerenv")
        or bool(os.environ.get("DOCKER_CONTAINER"))
        or bool(os.environ.get("DOCKER_IMAGE_NAME"))
    )


def find_gt_path(py_path: str) -> str | None:
    """Given a path to a `main.py` snippet, return the sibling `main_gt.json`
    if it exists (used by the stub path, never by the API path)."""
    gt_path = py_path.rsplit(".py", 1)[0] + "_gt.json"
    return gt_path if os.path.exists(gt_path) else None
