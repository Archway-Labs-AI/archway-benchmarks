"""supabase_mirror.py — best-effort mirror of a completed benchmark run into the shared
`archway-evals` Supabase Postgres store.

Called by each runner right after a run is committed to the local `runs.db`, so EVERY run
through archway-bench lands in the shared store automatically. The local `runs.db` stays the
full source of truth; this pushes a faithful copy (aggregate + per-case) to Postgres so every
machine/agent sees the same scorecard history.

Self-contained on purpose — no `archway-harness` import. The harness's `results_db.py` /
`eval_mirror.py` are sibling tools that write the SAME schema (the contract is the two tables):
  eval_runs(id, run_id, suite, ts, engine_sha, pin, branch, machine, workstream, totals jsonb)
  eval_results(id, run_pk→eval_runs.id, case_id, verdict, expected, passed, via, dims jsonb)

Behaviour:
  * Best-effort: any failure (no DSN, psycopg missing, network/quota) logs a warning and
    returns False — it NEVER breaks a benchmark run. Set ARCHWAY_EVALS_MIRROR=0 to disable.
  * Idempotent: re-mirroring a run replaces its prior copy.
  * Run-shape auto-detected from runs.db, so it covers TypeEvalPy (micro/autogen, external
    baselines — `scores`+`annotations`) AND BugsInPy (`bugsinpy_scores`+detection/repair).

DSN resolution: $ARCHWAY_EVALS_DSN → ./secrets/evals.env → <repo>/secrets/evals.env →
the sibling harness `../archway-agent-harness/secrets/evals.env`.
"""
from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterator

ENV_VAR = "ARCHWAY_EVALS_DSN"
DISABLE_VAR = "ARCHWAY_EVALS_MIRROR"          # set to "0" to skip mirroring
DEFAULT_REQUIRE_AUTH = "scram-sha-256"        # overrides the sandbox PGREQUIREAUTH=none
CONNECT_TIMEOUT = 15

_REPO_ROOT = Path(__file__).resolve().parents[2]  # archway-benchmarks/


class MirrorError(RuntimeError):
    pass


# --------------------------------------------------------------------------- DSN

def _secrets_candidates() -> list[Path]:
    return [
        Path.cwd() / "secrets" / "evals.env",
        _REPO_ROOT / "secrets" / "evals.env",
        _REPO_ROOT.parent / "archway-agent-harness" / "secrets" / "evals.env",
    ]


def load_dsn(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env = os.environ.get(ENV_VAR)
    if env:
        return env.strip()
    for path in _secrets_candidates():
        if path.exists():
            m = re.search(rf'{ENV_VAR}\s*=\s*"?([^"\n]+?)"?\s*$',
                          path.read_text(), re.MULTILINE)
            if m and "<" not in m.group(1):
                return m.group(1).strip()
    raise MirrorError(
        f"no DSN: set ${ENV_VAR} or create one of "
        f"{', '.join(str(p) for p in _secrets_candidates())}")


def _dsn_to_kwargs(dsn: str) -> dict[str, Any]:
    """Parse postgresql://user:password@host:port/db?k=v into psycopg kwargs.

    Password is taken literally (no URI percent-encoding pitfalls)."""
    from urllib.parse import unquote

    if not re.match(r"^postgres(ql)?://", dsn):
        return {"conninfo": dsn}
    after = dsn.split("://", 1)[1]
    userinfo, hostpart = after.rsplit("@", 1)
    user, _, password = userinfo.partition(":")
    netloc, _, tail = hostpart.partition("/")
    host, _, port = netloc.partition(":")
    dbname, _, query = tail.partition("?")
    kwargs: dict[str, Any] = {"user": unquote(user), "password": password,
                              "host": host, "dbname": dbname or "postgres"}
    if port:
        kwargs["port"] = port
    for kv in query.split("&"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            kwargs[k] = unquote(v)
    return kwargs


def _connect(dsn: str | None = None):
    try:
        import psycopg
    except ImportError as e:
        raise MirrorError("psycopg not installed (pip install 'psycopg[binary]')") from e
    kwargs = _dsn_to_kwargs(load_dsn(dsn))
    conninfo = kwargs.pop("conninfo", "")
    kwargs.setdefault("require_auth", DEFAULT_REQUIRE_AUTH)
    try:
        return psycopg.connect(conninfo, connect_timeout=CONNECT_TIMEOUT, **kwargs)
    except Exception as e:
        raise MirrorError(f"could not connect to the eval store: {e}") from e


# ----------------------------------------------------------------- read runs.db

_SUITE = {"typeevalpy": "typeevalpy-micro", "typeevalpy_autogen": "typeevalpy-autogen"}


def _suite(benchmark: str, mode: str | None = None) -> str:
    base = _SUITE.get(benchmark, benchmark)
    return f"{base}-{mode}" if mode else base


def _key(benchmark: str, run_id: int, mode: str | None = None) -> str:
    return f"{benchmark}#{run_id}" + (f":{mode}" if mode else "")


def _detect_shape(con: sqlite3.Connection, run_id: int) -> str:
    """'typeevalpy' (scores+annotations) | 'bugsinpy' (bugsinpy_scores) | 'bare'."""
    if con.execute("SELECT 1 FROM scores WHERE run_id=? LIMIT 1", (run_id,)).fetchone():
        return "typeevalpy"
    tbls = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "bugsinpy_scores" in tbls and con.execute(
            "SELECT 1 FROM bugsinpy_scores WHERE run_id=? LIMIT 1", (run_id,)).fetchone():
        return "bugsinpy"
    return "bare"


def _typeevalpy_totals(con: sqlite3.Connection, run: sqlite3.Row) -> dict[str, Any]:
    scopes: dict[str, Any] = {}
    headline: dict[str, Any] = {}
    for s in con.execute("SELECT * FROM scores WHERE run_id=?", (run["id"],)):
        total, exact = s["total_annotations"] or 0, s["exact_total"] or 0
        scopes[s["scope"]] = {"exact": exact, "total": total,
                              "exact_pct": (exact / total) if total else None,
                              "precision": s["annotation_precision"],
                              "recall": s["annotation_recall"]}
        if s["scope"] == "all":
            headline = {"exact": exact, "total": total,
                        "exact_pct": (exact / total) if total else None,
                        "precision": s["annotation_precision"],
                        "recall": s["annotation_recall"],
                        "by_category": json.loads(s["exact_by_category_json"] or "{}"),
                        "by_kind": json.loads(s["exact_by_kind_json"] or "{}")}
    return {**headline, "scopes": scopes}


def _typeevalpy_cases(con: sqlite3.Connection, run_id: int) -> Iterator[dict[str, Any]]:
    for a in con.execute("SELECT * FROM annotations WHERE run_id=?", (run_id,)):
        outcome = a["outcome"]
        yield {
            "case_id": f'{a["suite_path"]}|{a["file"]}|L{a["line"]}C{a["col"]}|{a["kind"]}:{a["name"]}',
            "verdict": outcome, "expected": a["expected_types"],
            "passed": outcome == "EXACT", "via": a["kind"],
            "dims": {"category": a["category"], "kind": a["kind"], "name": a["name"],
                     "function": a["function"], "file": a["file"], "line": a["line"],
                     "col": a["col"], "predicted_types": a["predicted_types"],
                     "suite_path": a["suite_path"]},
        }


def _bugsinpy_totals(con: sqlite3.Connection, run_id: int) -> tuple[dict[str, Any], str | None]:
    rows = list(con.execute("SELECT * FROM bugsinpy_scores WHERE run_id=?", (run_id,)))
    by_scope = {f'{r["mode"]}/{r["scope"]}': {"hit": r["hit"], "total": r["total_bugs"],
                "attempted": r["bugs_attempted"]} for r in rows}
    mode = rows[0]["mode"] if rows else None
    return {"scopes": by_scope}, mode


def _bugsinpy_cases(con: sqlite3.Connection, run_id: int) -> Iterator[dict[str, Any]]:
    for d in con.execute("SELECT * FROM bugsinpy_detection WHERE run_id=?", (run_id,)):
        yield {"case_id": d["bug_key"], "verdict": d["kind"],
               "passed": d["kind"] == "DETECTED", "via": "detection",
               "dims": {"project": d["project"], "bug_id": d["bug_id"],
                        "flagged_count": d["flagged_count"]}}
    for r in con.execute("SELECT * FROM bugsinpy_repair WHERE run_id=?", (run_id,)):
        yield {"case_id": r["bug_key"], "verdict": "PASS" if r["passed"] else "FAIL",
               "passed": bool(r["passed"]), "via": "repair",
               "dims": {"project": r["project"], "bug_id": r["bug_id"],
                        "n_tests": r["n_tests"], "n_passed": r["n_passed"]}}


# ----------------------------------------------------------------------- mirror

def mirror_completed_run(db_path: Path | str, run_id: int, *, with_cases: bool = True,
                         dsn: str | None = None) -> dict[str, Any]:
    """Mirror one runs.db run into Supabase (idempotent, single transaction). Raises on failure."""
    db_path = Path(db_path)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:  # keep the sqlite connection OPEN until the COPY has drained the cases generator
        run = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise MirrorError(f"no run {run_id} in {db_path}")
        meta = json.loads(run["metadata"] or "{}")
        shape = _detect_shape(con, run_id)
        if shape == "bugsinpy":
            agg, mode = _bugsinpy_totals(con, run_id)
            cases = _bugsinpy_cases(con, run_id) if with_cases else iter(())
        else:  # typeevalpy / external baselines / bare
            agg, mode = (_typeevalpy_totals(con, run) if shape == "typeevalpy" else {}), None
            cases = (_typeevalpy_cases(con, run_id)
                     if (with_cases and shape == "typeevalpy") else iter(()))
        totals = {"benchmark": run["benchmark"], "engine": run["engine"],
                  "notes": run["notes"], "metadata": meta, **agg}
        suite = _suite(run["benchmark"], mode)
        engine = run["engine"] or ""
        if engine.startswith("external:"):  # keep each baseline tool on its own suite axis
            suite = f"{suite}:{engine.split(':', 1)[1]}"
        key = _key(run["benchmark"], run_id, mode)
        cols = ["run_id", "suite", "engine_sha", "pin", "branch", "machine", "workstream",
                "ts", "totals"]
        vals: list[Any] = [key, suite, meta.get("engine_sha"), meta.get("pin"),
                           meta.get("branch"), socket.gethostname(),
                           os.environ.get("ARCHWAY_EVALS_WORKSTREAM", "archway-bench"),
                           run["created_at"], json.dumps(totals)]
        n = 0
        with _connect(dsn) as pg:
            with pg.cursor() as cur:
                cur.execute("SELECT id FROM eval_runs WHERE run_id=%s AND suite=%s", (key, suite))
                for (old,) in cur.fetchall():
                    cur.execute("DELETE FROM eval_results WHERE run_pk=%s", (old,))
                    cur.execute("DELETE FROM eval_runs WHERE id=%s", (old,))
                cur.execute(
                    f"INSERT INTO eval_runs ({', '.join(cols)}) "
                    f"VALUES ({', '.join(['%s'] * len(vals))}) RETURNING id", vals)
                pk = cur.fetchone()[0]
                if with_cases:
                    with cur.copy("COPY eval_results "
                                  "(run_pk, case_id, verdict, expected, passed, via, dims) "
                                  "FROM STDIN") as cp:
                        for c in cases:
                            cp.write_row((pk, c["case_id"], c.get("verdict"), c.get("expected"),
                                          c.get("passed"), c.get("via"),
                                          json.dumps(c.get("dims") or {})))
                            n += 1
        return {"run_id": run_id, "key": key, "suite": suite, "pk": pk, "cases": n}
    finally:
        con.close()


def mirror_safe(db_path: Path | str, run_id: int, *, with_cases: bool = True,
                dsn: str | None = None) -> bool:
    """Best-effort wrapper for the runners. Never raises; logs a one-line warning on failure."""
    if os.environ.get(DISABLE_VAR) == "0":
        return False
    try:
        r = mirror_completed_run(db_path, run_id, with_cases=with_cases, dsn=dsn)
        print(f"[supabase-mirror] ✓ run {run_id} -> {r['suite']} "
              f"({r['cases']} cases)", file=sys.stderr)
        return True
    except Exception as e:  # noqa: BLE001 — best-effort, must not break a benchmark run
        print(f"[supabase-mirror] ⚠ run {run_id} not mirrored: {e} "
              f"(local runs.db is unaffected; backfill later with "
              f"`python -m harness.eval_mirror --run {run_id} --with-cases`)", file=sys.stderr)
        return False


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Mirror a runs.db run into the shared Supabase store.")
    ap.add_argument("run_id", type=int)
    ap.add_argument("--db", default="runs.db")
    ap.add_argument("--no-cases", action="store_true", help="aggregate only")
    args = ap.parse_args(argv)
    ok = mirror_safe(args.db, args.run_id, with_cases=not args.no_cases)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
