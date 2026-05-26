"""Leaderboard data source.

`StaticLeaderboard` reads from `leaderboard/<benchmark>.json` (checked in).
`FetchedLeaderboard` is a placeholder for future scraping; today it returns
the static data so the dashboard never breaks if the dependency isn't there.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LeaderboardEntry:
    tool: str
    function_returns: int
    function_parameters: int
    local_variables: int
    exact_total: int


@dataclass(frozen=True)
class LeaderboardSnapshot:
    benchmark: str
    source: str
    total_annotations: int
    total_snippets: int
    kind_totals: dict[str, int]
    tools: tuple[LeaderboardEntry, ...]


class LeaderboardSource(Protocol):
    def get(self, benchmark: str) -> LeaderboardSnapshot: ...


class StaticLeaderboard:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (_REPO_ROOT / "leaderboard")

    def get(self, benchmark: str) -> LeaderboardSnapshot:
        path = self.root / f"{benchmark}.json"
        data = json.loads(path.read_text())
        return LeaderboardSnapshot(
            benchmark=data["benchmark"],
            source=data["source"],
            total_annotations=data["total_annotations"],
            total_snippets=data["total_snippets"],
            kind_totals=data["kind_totals"],
            tools=tuple(LeaderboardEntry(**t) for t in data["tools"]),
        )


class FetchedLeaderboard:
    """Stub for a future scraper. Currently delegates to the static file."""

    def __init__(self, fallback: LeaderboardSource | None = None) -> None:
        self._fallback = fallback or StaticLeaderboard()

    def get(self, benchmark: str) -> LeaderboardSnapshot:
        # TODO: scrape paper_table_*.csv from the vendored repo at HEAD
        # and reconcile with the static snapshot. For now, fall through.
        return self._fallback.get(benchmark)
