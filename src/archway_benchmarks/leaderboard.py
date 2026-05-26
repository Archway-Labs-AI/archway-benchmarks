"""Leaderboard data sources.

Three sources live behind a single `LeaderboardSource` Protocol:

- `StaticLeaderboard` — the published Aug-2024 board, scored against the
  *old* GT snapshot. Hardcoded in `leaderboard/<benchmark>.json`.
  Must remain the authoritative copy of those exact numbers; do not edit.
- `RegeneratedLeaderboard` — baselines we ran against the *current* GT.
  Reads runs from the harness store flagged as `engine LIKE 'external:%'`.
  This is the dashboard's like-for-like-with-Archway comparison.
- `FetchedLeaderboard` — placeholder for future scrapes from upstream.

The dashboard renders both Static and Regenerated side by side. **Never
conflate them** — the GT is different, so the numbers are not comparable
across columns even though both refer to the same tool.
"""
from __future__ import annotations

import json
import sqlite3
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
    files_sound: int | None = None
    files_complete: int | None = None
    runtime_seconds: float | None = None
    image_digest: str | None = None
    regenerated_at: str | None = None
    run_id: int | None = None
    # Lenient (publication-era scorer) counts — the comparison-friendly
    # numbers; see scoring/typeevalpy_lenient.py for provenance.
    exact_total_lenient: int | None = None
    function_returns_lenient: int | None = None
    function_parameters_lenient: int | None = None
    local_variables_lenient: int | None = None


@dataclass(frozen=True)
class LeaderboardSnapshot:
    benchmark: str
    source: str  # human-readable provenance string
    label: str  # short label for the dashboard column (e.g. "Published Aug 2024")
    total_annotations: int
    total_snippets: int
    kind_totals: dict[str, int]
    tools: tuple[LeaderboardEntry, ...]


class LeaderboardSource(Protocol):
    def get(self, benchmark: str) -> LeaderboardSnapshot | None: ...


class StaticLeaderboard:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (_REPO_ROOT / "leaderboard")

    def get(self, benchmark: str) -> LeaderboardSnapshot | None:
        path = self.root / f"{benchmark}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return LeaderboardSnapshot(
            benchmark=data["benchmark"],
            source=data["source"],
            label=data.get("label", "Published Aug 2024"),
            total_annotations=data["total_annotations"],
            total_snippets=data["total_snippets"],
            kind_totals=data["kind_totals"],
            tools=tuple(LeaderboardEntry(**t) for t in data["tools"]),
        )


class RegeneratedLeaderboard:
    """Aggregate external-baseline runs out of the harness store.

    A row exists per tool — the most recent run for that tool, keyed off
    `runs.engine LIKE 'external:%'` and `runs.benchmark = <benchmark>`.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def get(self, benchmark: str) -> LeaderboardSnapshot | None:
        if not self.db_path.exists():
            return None
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            # Latest external run per tool (by max run id).
            rows = conn.execute(
                """
                SELECT r.id AS run_id, r.engine, r.created_at, r.metadata,
                       s.total_snippets, s.total_annotations, s.exact_total,
                       s.files_sound, s.files_complete, s.exact_by_kind_json,
                       sl.exact_total AS exact_total_lenient,
                       sl.exact_by_kind_json AS exact_by_kind_lenient_json,
                       sl.files_sound AS files_sound_lenient,
                       sl.files_complete AS files_complete_lenient
                FROM runs r
                JOIN scores s ON s.run_id = r.id AND s.scope = 'all'
                LEFT JOIN scores sl ON sl.run_id = r.id AND sl.scope = 'all_lenient'
                WHERE r.benchmark = ?
                  AND r.engine LIKE 'external:%'
                  AND r.id IN (
                      SELECT MAX(id) FROM runs
                      WHERE benchmark = ? AND engine LIKE 'external:%'
                      GROUP BY engine
                  )
                ORDER BY COALESCE(sl.exact_total, s.exact_total) DESC
                """,
                (benchmark, benchmark),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return None

        entries: list[LeaderboardEntry] = []
        total_snippets = 0
        total_annotations = 0
        for r in rows:
            metadata = json.loads(r["metadata"]) if r["metadata"] else {}
            exact_by_kind = json.loads(r["exact_by_kind_json"])
            tool = (metadata.get("tool") or r["engine"].split(":", 1)[1]).strip()
            lenient_by_kind = (
                json.loads(r["exact_by_kind_lenient_json"])
                if r["exact_by_kind_lenient_json"]
                else {}
            )
            entries.append(
                LeaderboardEntry(
                    tool=tool,
                    function_returns=exact_by_kind.get("return", 0),
                    function_parameters=exact_by_kind.get("parameter", 0),
                    local_variables=exact_by_kind.get("variable", 0),
                    exact_total=r["exact_total"],
                    files_sound=r["files_sound"],
                    files_complete=r["files_complete"],
                    runtime_seconds=metadata.get("runtime_seconds"),
                    image_digest=metadata.get("image_digest"),
                    regenerated_at=metadata.get("regenerated_at"),
                    run_id=r["run_id"],
                    exact_total_lenient=r["exact_total_lenient"],
                    function_returns_lenient=lenient_by_kind.get("return"),
                    function_parameters_lenient=lenient_by_kind.get("parameter"),
                    local_variables_lenient=lenient_by_kind.get("variable"),
                )
            )
            total_snippets = r["total_snippets"]
            total_annotations = r["total_annotations"]

        return LeaderboardSnapshot(
            benchmark=benchmark,
            source=f"regenerated from harness store {self.db_path}, current GT",
            label="Regenerated · current GT",
            total_annotations=total_annotations,
            total_snippets=total_snippets,
            kind_totals={
                "function_returns": 0,
                "function_parameters": 0,
                "local_variables": 0,
            },  # derived from snapshot; per-row kind counts are the comparable cells
            tools=tuple(entries),
        )


class FetchedLeaderboard:
    """Stub for a future scraper. Currently delegates to the static file."""

    def __init__(self, fallback: LeaderboardSource | None = None) -> None:
        self._fallback = fallback or StaticLeaderboard()

    def get(self, benchmark: str) -> LeaderboardSnapshot | None:
        # TODO: scrape paper_table_*.csv from the vendored repo at HEAD
        # and reconcile with the static snapshot. For now, fall through.
        return self._fallback.get(benchmark)
