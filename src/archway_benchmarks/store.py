"""SQLite-backed result store.

Schema:

  runs            id, created_at, benchmark, engine, stub_accuracy, seed, notes
  snippets        run_id, suite_path, source, translation_status, error
  annotations     run_id, suite_path, file, line, col, kind, name, function,
                  category, expected_types, predicted_types, outcome,
                  is_function_parameter, is_callable_gt
  spurious        run_id, suite_path, file, line, col, kind, name, function,
                  predicted_types
  scores          run_id, scope, total_snippets, total_annotations,
                  files_sound, files_complete, exact_total,
                  annotation_precision, annotation_recall,
                  exact_by_kind_json, exact_by_category_json

All collections of types are stored as sorted-JSON arrays for stable diffs.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from archway_benchmarks.bugsinpy_types import (
    DetectionOutcome,
    DetectionScores,
    RepairScores,
    TestOutcome,
)
from archway_benchmarks.coverage import CoverageStatus
from archway_benchmarks.outcome import Outcome
from archway_benchmarks.scoring.typeevalpy import SnippetScores
from archway_benchmarks.types import Location, Scores

DEFAULT_DB_PATH = Path("runs.db")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    benchmark TEXT NOT NULL,
    engine TEXT NOT NULL,
    stub_accuracy REAL,
    seed INTEGER,
    notes TEXT,
    -- Free-form JSON for external-baseline metadata: tool, image_digest,
    -- benchmark_commit, runtime_seconds, sample_size, top_n, source, etc.
    metadata TEXT
);
-- Idempotent additive migration for existing DBs.
-- (SQLite ignores duplicate ADD COLUMN via this no-op pattern.)

CREATE TABLE IF NOT EXISTS snippets (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    suite_path TEXT NOT NULL,
    source TEXT NOT NULL,
    translation_status TEXT NOT NULL,
    error TEXT,
    PRIMARY KEY (run_id, suite_path)
);

CREATE TABLE IF NOT EXISTS annotations (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    suite_path TEXT NOT NULL,
    file TEXT NOT NULL,
    line INTEGER NOT NULL,
    col INTEGER NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    function TEXT,
    category TEXT NOT NULL,
    expected_types TEXT NOT NULL,
    predicted_types TEXT,
    outcome TEXT NOT NULL,
    is_function_parameter INTEGER NOT NULL,
    is_callable_gt INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_annotations_run ON annotations(run_id);
CREATE INDEX IF NOT EXISTS idx_annotations_outcome ON annotations(run_id, outcome);
CREATE INDEX IF NOT EXISTS idx_annotations_category ON annotations(run_id, category);

CREATE TABLE IF NOT EXISTS spurious (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    suite_path TEXT NOT NULL,
    file TEXT NOT NULL,
    line INTEGER NOT NULL,
    col INTEGER NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    function TEXT,
    predicted_types TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spurious_run ON spurious(run_id);

CREATE TABLE IF NOT EXISTS scores (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    total_snippets INTEGER NOT NULL,
    total_annotations INTEGER NOT NULL,
    files_sound INTEGER NOT NULL,
    files_complete INTEGER NOT NULL,
    exact_total INTEGER NOT NULL,
    annotation_precision REAL NOT NULL,
    annotation_recall REAL NOT NULL,
    exact_by_kind_json TEXT NOT NULL,
    exact_by_category_json TEXT NOT NULL,
    -- Rule-bucket × kind cross-tab. JSON: {bucket: {kind: caught}}.
    -- Nullable so legacy rows can be migrated/backfilled.
    exact_by_bucket_kind_json TEXT,
    PRIMARY KEY (run_id, scope)
);

-- ===== BugsInPy (parallel benchmark; shares `runs`) =====
-- A BugsInPy run is a `runs` row with benchmark='bugsinpy' and provenance in
-- `runs.metadata` JSON: {mode, engine_sha, corpus_commit, subset, ...}. Its
-- per-bug results + aggregate land in the tables below, mirroring how
-- TypeEvalPy uses annotations/spurious/scores. Created here (IF NOT EXISTS) so
-- existing DBs gain them on next connect — no separate migration needed.

CREATE TABLE IF NOT EXISTS bugsinpy_detection (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    project TEXT NOT NULL,
    bug_id TEXT NOT NULL,
    bug_key TEXT NOT NULL,
    kind TEXT NOT NULL,                 -- DETECTED | WRONG_FILE | MISSED
    flagged_count INTEGER NOT NULL,
    matched_locations_json TEXT NOT NULL,
    PRIMARY KEY (run_id, bug_key)
);
CREATE INDEX IF NOT EXISTS idx_bugsinpy_detection_run ON bugsinpy_detection(run_id);

CREATE TABLE IF NOT EXISTS bugsinpy_repair (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    project TEXT NOT NULL,
    bug_id TEXT NOT NULL,
    bug_key TEXT NOT NULL,
    passed INTEGER NOT NULL,            -- 1 iff all previously-failing tests pass
    n_tests INTEGER NOT NULL,
    n_passed INTEGER NOT NULL,
    n_failed INTEGER NOT NULL,
    detail TEXT,
    PRIMARY KEY (run_id, bug_key)
);
CREATE INDEX IF NOT EXISTS idx_bugsinpy_repair_run ON bugsinpy_repair(run_id);

CREATE TABLE IF NOT EXISTS bugsinpy_scores (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    mode TEXT NOT NULL,                 -- detection | repair
    scope TEXT NOT NULL,                -- all | subset
    total_bugs INTEGER NOT NULL,
    bugs_attempted INTEGER NOT NULL,
    hit INTEGER NOT NULL,               -- detected (detection) | repaired (repair)
    file_level_detected INTEGER,        -- detection only; NULL for repair
    by_project_json TEXT NOT NULL,      -- {project: hit}
    total_by_project_json TEXT NOT NULL,
    PRIMARY KEY (run_id, mode, scope)
);

-- DIRECTIONAL bucketer output. Keyed by (bug_key, bucketer_version), NOT run_id:
-- a bucket is a property of the BUG (its patch), so re-running the bucketer
-- re-buckets the SAME stored detection results WITHOUT a benchmark re-run. Report
-- time JOINs bugsinpy_detection (per run) × this (per version). NOT claim-grade.
CREATE TABLE IF NOT EXISTS bugsinpy_buckets (
    bug_key TEXT NOT NULL,
    bucketer_version TEXT NOT NULL,
    project TEXT NOT NULL,
    bucket TEXT NOT NULL,               -- one of bugsinpy_bucketer.BUCKET_CLASSES
    confidence TEXT NOT NULL,           -- high | low
    evidence TEXT,                      -- matched pattern + sample line (for a human check)
    PRIMARY KEY (bug_key, bucketer_version)
);
CREATE INDEX IF NOT EXISTS idx_bugsinpy_buckets_version ON bugsinpy_buckets(bucketer_version);
"""


@dataclass(frozen=True)
class RunHeader:
    id: int
    created_at: str
    benchmark: str
    engine: str
    stub_accuracy: float | None
    seed: int | None
    notes: str | None
    metadata: str | None = None


# ----- connection management -----

@contextmanager
def connect(path: Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply additive migrations; safe to call repeatedly."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "metadata" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN metadata TEXT")
    score_cols = {r["name"] for r in conn.execute("PRAGMA table_info(scores)").fetchall()}
    if "exact_by_bucket_kind_json" not in score_cols:
        conn.execute("ALTER TABLE scores ADD COLUMN exact_by_bucket_kind_json TEXT")
    if "files_processed" not in score_cols:
        # Nullable so legacy rows can be migrated/backfilled if anyone cares;
        # otherwise readers treat NULL the same as "unknown" and report a dash.
        conn.execute("ALTER TABLE scores ADD COLUMN files_processed INTEGER")


# ----- writers -----

def create_run(
    conn: sqlite3.Connection,
    *,
    benchmark: str,
    engine: str,
    stub_accuracy: float | None,
    seed: int | None,
    notes: str | None = None,
    metadata: dict | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO runs (created_at, benchmark, engine, stub_accuracy, seed, notes, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            benchmark,
            engine,
            stub_accuracy,
            seed,
            notes,
            json.dumps(metadata) if metadata is not None else None,
        ),
    )
    return int(cur.lastrowid)


def record_snippet(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    suite_path: str,
    source: str,
    translation_status: CoverageStatus,
    error: str | None = None,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO snippets "
        "(run_id, suite_path, source, translation_status, error) VALUES (?, ?, ?, ?, ?)",
        (run_id, suite_path, source, translation_status.value, error),
    )


def record_snippet_scores(
    conn: sqlite3.Connection,
    run_id: int,
    per_snippet: Iterable[SnippetScores],
    *,
    callable_locations: set[Location] | None = None,
) -> None:
    callable_locations = callable_locations or set()
    for snip in per_snippet:
        for o in snip.outcomes:
            conn.execute(
                "INSERT INTO annotations "
                "(run_id, suite_path, file, line, col, kind, name, function, category, "
                " expected_types, predicted_types, outcome, is_function_parameter, is_callable_gt) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    snip.suite_path,
                    o.location.file,
                    o.location.line,
                    o.location.col or 0,
                    o.location.kind,
                    o.location.name,
                    o.location.function,
                    o.category,
                    json.dumps(sorted(o.expected_types)),
                    json.dumps(sorted(o.predicted_types)) if o.predicted_types is not None else None,
                    o.outcome.value,
                    1 if o.location.kind == "parameter" else 0,
                    1 if o.expected_types == frozenset({"callable"}) else 0,
                ),
            )
        for loc, types in snip.spurious_predictions:
            conn.execute(
                "INSERT INTO spurious "
                "(run_id, suite_path, file, line, col, kind, name, function, predicted_types) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    snip.suite_path,
                    loc.file,
                    loc.line,
                    loc.col or 0,
                    loc.kind,
                    loc.name,
                    loc.function,
                    json.dumps(sorted(types)),
                ),
            )


def record_scores(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    scope: str,
    scores: Scores,
) -> None:
    if scope not in {"all", "covered", "all_lenient", "covered_lenient"}:
        raise ValueError(f"unknown scope: {scope}")
    conn.execute(
        "INSERT OR REPLACE INTO scores "
        "(run_id, scope, total_snippets, total_annotations, files_sound, files_complete, "
        " exact_total, annotation_precision, annotation_recall, "
        " exact_by_kind_json, exact_by_category_json, exact_by_bucket_kind_json, "
        " files_processed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            scope,
            scores.total_snippets,
            scores.total_annotations,
            scores.files_sound,
            scores.files_complete,
            scores.exact_total,
            scores.annotation_precision,
            scores.annotation_recall,
            json.dumps(scores.exact_by_kind),
            json.dumps(scores.exact_by_category),
            json.dumps(scores.exact_by_bucket_kind) if scores.exact_by_bucket_kind else None,
            scores.files_processed,
        ),
    )


# ----- BugsInPy writers (parallel benchmark; reuse `create_run`) -----

def record_bugsinpy_detection(
    conn: sqlite3.Connection,
    run_id: int,
    outcomes: Iterable[DetectionOutcome],
) -> None:
    for o in outcomes:
        _, _, bug_id = o.bug_key.partition(":")
        conn.execute(
            "INSERT OR REPLACE INTO bugsinpy_detection "
            "(run_id, project, bug_id, bug_key, kind, flagged_count, matched_locations_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id, o.project, bug_id, o.bug_key, o.kind, o.flagged_count,
                json.dumps([
                    {"file": m.file, "start": m.start, "end": m.end, "lines": sorted(m.lines)}
                    for m in o.matched_locations
                ]),
            ),
        )


def record_bugsinpy_repair(
    conn: sqlite3.Connection,
    run_id: int,
    outcomes: Iterable[TestOutcome],
) -> None:
    for o in outcomes:
        _, _, bug_id = o.bug_key.partition(":")
        conn.execute(
            "INSERT OR REPLACE INTO bugsinpy_repair "
            "(run_id, project, bug_id, bug_key, passed, n_tests, n_passed, n_failed, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, o.project, bug_id, o.bug_key, 1 if o.passed else 0,
             o.n_tests, o.n_passed, o.n_failed, o.detail),
        )


def record_bugsinpy_scores(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    mode: str,
    scope: str,
    scores: DetectionScores | RepairScores,
) -> None:
    if mode not in {"detection", "repair"}:
        raise ValueError(f"unknown bugsinpy mode: {mode}")
    if scope not in {"all", "subset"}:
        raise ValueError(f"unknown scope: {scope}")
    if isinstance(scores, DetectionScores):
        hit, file_level = scores.detected, scores.file_level_detected
        by_project, total_by_project = scores.detected_by_project, scores.total_by_project
    else:
        hit, file_level = scores.repaired, None
        by_project, total_by_project = scores.repaired_by_project, scores.total_by_project
    conn.execute(
        "INSERT OR REPLACE INTO bugsinpy_scores "
        "(run_id, mode, scope, total_bugs, bugs_attempted, hit, file_level_detected, "
        " by_project_json, total_by_project_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, mode, scope, scores.total_bugs, scores.bugs_attempted, hit, file_level,
         json.dumps(by_project), json.dumps(total_by_project)),
    )


def get_bugsinpy_scores(conn: sqlite3.Connection, run_id: int) -> dict[tuple[str, str], dict]:
    """`(mode, scope) -> score row` for a BugsInPy run."""
    rows = conn.execute(
        "SELECT * FROM bugsinpy_scores WHERE run_id = ?", (run_id,)
    ).fetchall()
    return {(r["mode"], r["scope"]): dict(r) for r in rows}


def list_bugsinpy_detection(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM bugsinpy_detection WHERE run_id = ? ORDER BY project, bug_id",
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_bugsinpy_repair(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM bugsinpy_repair WHERE run_id = ? ORDER BY project, bug_id",
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def record_bugsinpy_buckets(conn: sqlite3.Connection, results) -> None:
    """Store DIRECTIONAL bucket results, keyed by (bug_key, bucketer_version).

    INSERT OR REPLACE so re-running the SAME version overwrites in place, and a
    NEW version coexists — both kept, so reports can compare versions. `results`
    is any iterable of `bugsinpy_bucketer.BucketResult` (duck-typed)."""
    for r in results:
        conn.execute(
            "INSERT OR REPLACE INTO bugsinpy_buckets "
            "(bug_key, bucketer_version, project, bucket, confidence, evidence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (r.bug_key, r.bucketer_version, r.project, r.bucket, r.confidence, r.evidence),
        )


def get_bugsinpy_buckets(conn: sqlite3.Connection, version: str) -> dict[str, dict]:
    """`bug_key -> bucket row` for one bucketer version."""
    rows = conn.execute(
        "SELECT * FROM bugsinpy_buckets WHERE bucketer_version = ?", (version,)
    ).fetchall()
    return {r["bug_key"]: dict(r) for r in rows}


def list_bugsinpy_bucket_versions(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT bucketer_version FROM bugsinpy_buckets ORDER BY bucketer_version"
    ).fetchall()
    return [r["bucketer_version"] for r in rows]


# ----- readers -----

def list_runs(conn: sqlite3.Connection) -> list[RunHeader]:
    rows = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
    return [RunHeader(**dict(r)) for r in rows]


def get_run(conn: sqlite3.Connection, run_id: int) -> RunHeader | None:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return RunHeader(**dict(row)) if row else None


def get_scores(
    conn: sqlite3.Connection, run_id: int
) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT * FROM scores WHERE run_id = ?", (run_id,)
    ).fetchall()
    return {r["scope"]: dict(r) for r in rows}


def list_annotations(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    outcome: Outcome | None = None,
    category: str | None = None,
    kind: str | None = None,
    only_function_parameter: bool = False,
    only_callable_gt: bool = False,
) -> list[dict]:
    sql = "SELECT * FROM annotations WHERE run_id = ?"
    params: list = [run_id]
    if outcome:
        sql += " AND outcome = ?"
        params.append(outcome.value)
    if category:
        sql += " AND category = ?"
        params.append(category)
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    if only_function_parameter:
        sql += " AND is_function_parameter = 1"
    if only_callable_gt:
        sql += " AND is_callable_gt = 1"
    sql += " ORDER BY suite_path, line, col"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_snippet(
    conn: sqlite3.Connection, run_id: int, suite_path: str
) -> dict | None:
    row = conn.execute(
        "SELECT * FROM snippets WHERE run_id = ? AND suite_path = ?",
        (run_id, suite_path),
    ).fetchone()
    return dict(row) if row else None


def list_snippets(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM snippets WHERE run_id = ? ORDER BY suite_path",
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_spurious(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM spurious WHERE run_id = ? ORDER BY suite_path, line, col",
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]
