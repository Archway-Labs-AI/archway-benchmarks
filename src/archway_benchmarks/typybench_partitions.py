"""Frozen evaluation partitions for TypyBench development and holdouts."""

from __future__ import annotations


HOLDOUT_VERSION = "typybench-holdout-v1"
HOLDOUT_REPOSITORIES = frozenset((
    "AutoGPT",
    "haystack",
    "manim",
    "openai-python",
    "private-gpt",
    "rich",
    "streamlit",
    "supervision",
    "taipy",
    "urllib3",
))


def typybench_partition(repository: str) -> str:
    """Classify a repository without inspecting its analysis outcome."""

    return "holdout" if repository in HOLDOUT_REPOSITORIES else "development"
