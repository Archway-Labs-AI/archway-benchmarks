"""BugsInPy reports — per-run + progress, parallel to `reports.py` + cli `_progress_markdown`.

Reads everything from the SAME SQLite store (the `bugsinpy_*` tables + `runs`).
Renders a BugsInPy section the way TypeEvalPy renders, with provenance
(engine_sha, corpus_commit, mode, subset — read from `runs.metadata`) front and
center so any future number is never a cold figure.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _provenance(meta_json: str | None) -> dict:
    try:
        return json.loads(meta_json) if meta_json else {}
    except json.JSONDecodeError:
        return {}


def _prov_line(prov: dict) -> str:
    """One-line provenance stamp — the honesty discipline for any BugsInPy run."""
    bits = [
        f"mode `{prov.get('mode', '?')}`",
        f"engine_sha `{(prov.get('engine_sha') or '?')[:12]}`",
        f"corpus_commit `{(prov.get('corpus_commit') or '?')[:12]}`",
    ]
    subset = prov.get("subset")
    if subset and subset != "all":
        n = len(subset) if isinstance(subset, list) else subset
        bits.append(f"subset `{n}` bugs" if isinstance(subset, list) else f"subset `{subset}`")
    else:
        bits.append("subset `full corpus`")
    return " · ".join(bits)


# ----- per-run report -----

def render_run_report(db_path: Path | str, run_id: int) -> str:
    with _connect(db_path) as conn:
        run = conn.execute(
            "SELECT id, created_at, benchmark, engine, notes, metadata FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if run is None:
            raise SystemExit(f"run #{run_id} not found")
        prov = _provenance(run["metadata"])
        scores = conn.execute(
            "SELECT * FROM bugsinpy_scores WHERE run_id = ?", (run_id,)
        ).fetchall()

        lines = [f"# BugsInPy run #{run['id']} — {run['engine']}", "",
                 f"_Created {run['created_at']}_" + (f" · _{run['notes']}_" if run["notes"] else ""),
                 "", f"**Provenance:** {_prov_line(prov)}", ""]

        for s in scores:
            mode, scope = s["mode"], s["scope"]
            denom = s["total_bugs"] or 1
            rate = s["hit"] / denom
            label = "detected" if mode == "detection" else "repaired"
            lines.append(f"## {mode.title()} · scope `{scope}`")
            lines.append("")
            lines.append(f"- **{label.title()}:** {s['hit']} / {s['total_bugs']} ({rate:.1%})")
            lines.append(f"- **Attempted:** {s['bugs_attempted']} / {s['total_bugs']}")
            if mode == "detection" and s["file_level_detected"] is not None:
                lines.append(f"- **File-level hit:** {s['file_level_detected']} / {s['total_bugs']}")
            by_project = json.loads(s["by_project_json"] or "{}")
            total_by_project = json.loads(s["total_by_project_json"] or "{}")
            if total_by_project:
                lines.append("")
                lines.append("| Project | " + label.title() + " | Total | Rate |")
                lines.append("| --- | ---: | ---: | ---: |")
                for proj in sorted(total_by_project):
                    h = by_project.get(proj, 0)
                    t = total_by_project[proj]
                    lines.append(f"| {proj} | {h} | {t} | {h / t if t else 0:.0%} |")
            lines.append("")
    return "\n".join(lines)


# ----- progress report (mirrors cli `_progress_markdown`) -----

def render_progress(db_path: Path | str, *, mode: str | None = None) -> str:
    """Full BugsInPy history, newest-first — the analog of `archway_progress.md`.

    One row per (run, mode, scope) with provenance + subset, so 'subset AND full'
    are both visible rather than a single number.
    """
    with _connect(db_path) as conn:
        runs = conn.execute(
            "SELECT id, created_at, engine, notes, metadata FROM runs "
            "WHERE benchmark = 'bugsinpy' ORDER BY id DESC"
        ).fetchall()
        rows: list[tuple] = []
        for r in runs:
            prov = _provenance(r["metadata"])
            for s in conn.execute(
                "SELECT * FROM bugsinpy_scores WHERE run_id = ? ORDER BY mode, scope", (r["id"],)
            ).fetchall():
                if mode and s["mode"] != mode:
                    continue
                rows.append((r, prov, s))

    lines = ["# Archway on BugsInPy — Progress", ""]
    if not rows:
        lines.append("_No BugsInPy runs recorded yet. The machinery is in place; "
                     "no run, no numbers (by design)._")
        lines.append("")
        return "\n".join(lines)

    latest = rows[0]
    r, prov, s = latest
    denom = s["total_bugs"] or 1
    label = "detected" if s["mode"] == "detection" else "repaired"
    lines.append(
        f"**Current:** {s['hit']} / {s['total_bugs']} {label} ({s['hit']/denom:.1%}) "
        f"· {s['mode']} · scope `{s['scope']}` · run #{r['id']} ({r['created_at'][:19]})"
    )
    lines.append("")
    lines.append("_Columns: **Mode** detection|repair · **Hit** = bugs detected (right "
                 "location) or repaired (failing tests pass) · **Scope** full|subset · "
                 "provenance binds every number to engine_sha + corpus_commit._")
    lines.append("")
    lines.append("| # | Created | Mode | Scope | Hit | Total | Rate | engine_sha | corpus_commit | Notes |")
    lines.append("|---:|---|---|---|---:|---:|---:|---|---|---|")
    for r, prov, s in rows:
        denom = s["total_bugs"] or 1
        notes = (r["notes"] or "").replace("|", "\\|")
        lines.append(
            f"| {r['id']} | {r['created_at'][:19]} | {s['mode']} | {s['scope']} | "
            f"{s['hit']} | {s['total_bugs']} | {s['hit']/denom:.0%} | "
            f"`{(prov.get('engine_sha') or '?')[:12]}` | "
            f"`{(prov.get('corpus_commit') or '?')[:12]}` | {notes} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_progress(db_path: Path | str, out_path: Path | str, *, mode: str | None = None) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_progress(db_path, mode=mode))
    return out


# ----- detection BY directional bucket (JOIN run × bucketer version) -----

def render_detection_by_bucket(db_path: Path | str, run_id: int, *, version: str) -> str:
    """Join a detection run's per-bug outcomes with the bucketer's classes.

    Reports detection rate × class with the bucketer version + confidence
    visible, plus the needs-adjudication queue. Labelled DIRECTIONAL — the
    buckets are diagnostic, not claim-grade. Re-runnable against a NEW bucketer
    version with the SAME stored detection results (no benchmark re-run)."""
    from archway_benchmarks.bugsinpy_bucketer import BUCKET_CLASSES, DIRECTIONAL_NOTE

    with _connect(db_path) as conn:
        det = conn.execute(
            "SELECT bug_key, project, kind FROM bugsinpy_detection WHERE run_id = ?", (run_id,)
        ).fetchall()
        buckets = {
            r["bug_key"]: dict(r)
            for r in conn.execute(
                "SELECT bug_key, bucket, confidence, evidence FROM bugsinpy_buckets "
                "WHERE bucketer_version = ?", (version,)
            ).fetchall()
        }

    if not det:
        return f"# BugsInPy detection × bucket — run #{run_id}\n\n_No detection results for this run._\n"

    # per-bucket totals/detected + confidence tally
    agg: dict[str, dict] = {c: {"total": 0, "detected": 0, "high": 0, "low": 0} for c in BUCKET_CLASSES}
    adjudicate: list[tuple] = []
    unbucketed = 0
    for d in det:
        b = buckets.get(d["bug_key"])
        if b is None:
            unbucketed += 1
            continue
        cell = agg.setdefault(b["bucket"], {"total": 0, "detected": 0, "high": 0, "low": 0})
        cell["total"] += 1
        if d["kind"] == "DETECTED":
            cell["detected"] += 1
        cell[b["confidence"]] += 1
        if b["confidence"] == "low" or b["bucket"] == "api_misuse_lib":
            adjudicate.append((d["bug_key"], b["bucket"], b["confidence"], d["kind"], b.get("evidence", "")))

    lines = [
        f"# BugsInPy detection × directional bucket — run #{run_id}",
        "",
        f"> **{DIRECTIONAL_NOTE}**  Bucketer version: `{version}`.",
        "",
        "| Bucket | Detected | Total | Rate | conf high | conf low |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for c in BUCKET_CLASSES:
        cell = agg[c]
        if cell["total"] == 0:
            continue
        rate = cell["detected"] / cell["total"]
        lines.append(f"| {c} | {cell['detected']} | {cell['total']} | {rate:.0%} | "
                     f"{cell['high']} | {cell['low']} |")
    if unbucketed:
        lines.append(f"| _(unbucketed — no bucket for version `{version}`)_ | | {unbucketed} | | | |")

    lines += ["", f"## Needs adjudication ({len(adjudicate)})", "",
              "_Low-confidence or `api_misuse_lib` bugs — a human must confirm the class "
              "before any of these counts as claim-grade._", ""]
    if adjudicate:
        lines += ["| Bug | Bucket | Confidence | Detection | Evidence |",
                  "| --- | --- | --- | --- | --- |"]
        for key, bucket, conf, kind, ev in adjudicate:
            lines.append(f"| `{key}` | {bucket} | {conf} | {kind} | `{ev[:80]}` |")
    else:
        lines.append("_None._")
    lines.append("")
    return "\n".join(lines)


def write_detection_by_bucket(db_path: Path | str, run_id: int, out_path: Path | str,
                              *, version: str) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_detection_by_bucket(db_path, run_id, version=version))
    return out
