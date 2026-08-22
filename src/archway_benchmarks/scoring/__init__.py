"""Scoring package exports without eagerly loading optional benchmark assets."""

from __future__ import annotations


def __getattr__(name: str):
    if name in __all__:
        from archway_benchmarks.scoring import typeevalpy

        return getattr(typeevalpy, name)
    raise AttributeError(name)

__all__ = [
    "AnnotationOutcome",
    "SnippetScores",
    "score_predictions",
    "score_snippet",
]
