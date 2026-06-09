"""Per-run detailed markdown report.

Reads everything from the SQLite store — no live server probe needed. Produces
a single markdown file with:

  - Headline scores (exact / processed / sound / complete)
  - Outcome breakdown by GT kind
  - Per-category exact-rate (TypeEvalPy `python_features/<bucket>`)
  - TYPE_MISS pattern bucket (expected -> predicted)
  - Translation-error breakdown (grouped by error class, with snippets)
  - Optional: full per-annotation list of every non-EXACT outcome

The translation-error section only renders for runs where `snippets.error`
is populated — currently Archway runs (the runner captures the engine's
soft `result.error`). External-baseline runs leave it empty.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


# ----- data extraction -----


@dataclass(frozen=True)
class RunMeta:
    id: int
    created_at: str
    benchmark: str
    engine: str
    notes: str | None


def _connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _run_meta(conn: sqlite3.Connection, run_id: int) -> RunMeta:
    row = conn.execute(
        "SELECT id, created_at, benchmark, engine, notes FROM runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"run #{run_id} not found in store")
    return RunMeta(**dict(row))


def _scores(conn: sqlite3.Connection, run_id: int) -> dict:
    row = conn.execute(
        "SELECT total_snippets, total_annotations, files_sound, files_complete, "
        "files_processed, exact_total, annotation_precision, annotation_recall, "
        "exact_by_kind_json, exact_by_category_json "
        "FROM scores WHERE run_id = ? AND scope = 'all'",
        (run_id,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"no scores for run #{run_id}")
    d = dict(row)
    d["exact_by_kind"] = json.loads(d.pop("exact_by_kind_json") or "{}")
    d["exact_by_category"] = json.loads(d.pop("exact_by_category_json") or "{}")
    return d


# ----- section renderers -----


def _headline(meta: RunMeta, s: dict) -> str:
    rate = s["exact_total"] / s["total_annotations"] if s["total_annotations"] else 0.0
    return (
        f"# Run #{meta.id} — {meta.benchmark} · {meta.engine}\n"
        f"\n"
        f"_Created {meta.created_at}_"
        + (f" · _{meta.notes}_" if meta.notes else "")
        + "\n\n"
        f"- **Exact:** {s['exact_total']} / {s['total_annotations']} ({rate:.1%})\n"
        f"- **Files processed:** {s['files_processed']} / {s['total_snippets']}\n"
        f"- **Files sound:** {s['files_sound']} / {s['total_snippets']}\n"
        f"- **Files complete:** {s['files_complete']} / {s['total_snippets']}\n"
        f"- **Annotation precision:** {s['annotation_precision']:.3f}\n"
        f"- **Annotation recall:** {s['annotation_recall']:.3f}\n"
    )


def _outcome_breakdown(conn: sqlite3.Connection, run_id: int) -> str:
    rows = conn.execute(
        "SELECT kind, outcome, COUNT(*) AS n FROM annotations "
        "WHERE run_id = ? GROUP BY kind, outcome ORDER BY kind, outcome",
        (run_id,),
    ).fetchall()
    by_kind: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by_kind[r["kind"]][r["outcome"]] = r["n"]
    kinds = sorted(by_kind)
    outs = ["EXACT", "TYPE_MISS", "LOCATION_MISS"]
    lines = ["## Outcome breakdown", "", "| Kind | " + " | ".join(outs) + " | Total |",
             "| --- | " + " | ".join(["---:"] * (len(outs) + 1)) + " |"]
    for k in kinds:
        row = by_kind[k]
        total = sum(row.values())
        lines.append("| " + k + " | " + " | ".join(str(row.get(o, 0)) for o in outs) + f" | {total} |")
    return "\n".join(lines) + "\n"


def _per_category(s: dict, conn: sqlite3.Connection, run_id: int) -> str:
    # exact_by_category counts the EXACTs only; pair with total annotations
    # per category to get the rate.
    totals_rows = conn.execute(
        "SELECT category, COUNT(*) AS n FROM annotations WHERE run_id = ? GROUP BY category",
        (run_id,),
    ).fetchall()
    totals = {r["category"]: r["n"] for r in totals_rows}
    exact = s["exact_by_category"]
    rows = []
    for cat in sorted(totals):
        n = totals[cat]
        e = exact.get(cat, 0)
        rows.append((cat, e, n, e / n if n else 0.0))
    rows.sort(key=lambda r: r[3])  # worst first
    lines = ["## Per-category accuracy (worst first)", "",
             "| Category | Exact | Total | Rate |", "| --- | ---: | ---: | ---: |"]
    for cat, e, n, rate in rows:
        lines.append(f"| {cat} | {e} | {n} | {rate:.0%} |")
    return "\n".join(lines) + "\n"


def _type_miss_patterns(conn: sqlite3.Connection, run_id: int, limit: int = 30) -> str:
    rows = conn.execute(
        "SELECT expected_types, predicted_types, COUNT(*) AS n "
        "FROM annotations WHERE run_id = ? AND outcome = 'TYPE_MISS' "
        "GROUP BY expected_types, predicted_types ORDER BY n DESC, expected_types",
        (run_id,),
    ).fetchall()
    if not rows:
        return "## TYPE_MISS patterns\n\n_None._\n"
    lines = ["## TYPE_MISS patterns (top by count)", "",
             "| Expected | Predicted | Count |", "| --- | --- | ---: |"]
    total = 0
    for r in rows[:limit]:
        lines.append(f"| `{r['expected_types']}` | `{r['predicted_types']}` | {r['n']} |")
        total += r["n"]
    if len(rows) > limit:
        rest = sum(r["n"] for r in rows[limit:])
        lines.append(f"| _(+{len(rows)-limit} more)_ | | {rest} |")
        total += rest
    lines.append(f"| **Total TYPE_MISS** | | **{total}** |")
    return "\n".join(lines) + "\n"


# Strip common runtime noise from an error message so similar errors group.
def _normalize_error(msg: str) -> tuple[str, str]:
    """Return (error_class, normalized_detail).

    Trims memory addresses, large hex ids, and trailing structural detail
    so two snippets that hit the same handler-missing path show up as one.
    """
    if not msg:
        return ("unknown", "")
    cls, _, rest = msg.partition(":")
    detail = rest.strip()
    # Truncate after the first parenthesis or 80 chars to collapse variants.
    cut = detail.find("(")
    if 0 < cut < 80:
        detail = detail[:cut].rstrip()
    if len(detail) > 80:
        detail = detail[:80].rstrip() + "…"
    return (cls.strip(), detail)


def _translation_errors(conn: sqlite3.Connection, run_id: int) -> str:
    rows = conn.execute(
        "SELECT suite_path, error FROM snippets "
        "WHERE run_id = ? AND error IS NOT NULL AND error != '' "
        "ORDER BY suite_path",
        (run_id,),
    ).fetchall()
    if not rows:
        return "## Translation errors\n\n_None recorded. Either every snippet translated or this run's engine doesn't surface errors._\n"

    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in rows:
        key = _normalize_error(r["error"])
        grouped[key].append(r["suite_path"])

    items = sorted(grouped.items(), key=lambda kv: -len(kv[1]))
    total = sum(len(v) for v in grouped.values())
    lines = [
        f"## Translation errors ({total} snippets)",
        "",
        "Grouped by error class + leading detail; snippets that translated cleanly but produced no GT-matching wires are NOT in this list.",
        "",
        "| Error class | Detail | Count |",
        "| --- | --- | ---: |",
    ]
    for (cls, detail), snips in items:
        d = detail if detail else "_(no detail)_"
        lines.append(f"| `{cls}` | `{d}` | {len(snips)} |")
    lines.append("")
    lines.append("### Snippet lists per error class")
    lines.append("")
    for (cls, detail), snips in items:
        d = detail if detail else "(no detail)"
        lines.append(f"**`{cls}: {d}`** ({len(snips)})")
        lines.append("")
        for sp in snips:
            lines.append(f"- `{sp}`")
        lines.append("")
    return "\n".join(lines)


def _miss_listing(conn: sqlite3.Connection, run_id: int) -> str:
    rows = conn.execute(
        "SELECT suite_path, line, col, kind, name, expected_types, predicted_types, outcome "
        "FROM annotations WHERE run_id = ? AND outcome != 'EXACT' "
        "ORDER BY suite_path, line, col",
        (run_id,),
    ).fetchall()
    if not rows:
        return ""
    lines = [
        f"## All non-EXACT annotations ({len(rows)})",
        "",
        "| Suite | Line | Col | Kind | Name | Expected | Predicted | Outcome |",
        "| --- | ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        pred = r["predicted_types"] or ""
        lines.append(
            f"| `{r['suite_path']}` | {r['line']} | {r['col']} | "
            f"{r['kind']} | `{r['name']}` | `{r['expected_types']}` | "
            f"`{pred}` | {r['outcome']} |"
        )
    return "\n".join(lines) + "\n"


# ----- entrypoint -----


def render_report(
    db_path: Path | str,
    run_id: int,
    *,
    include_miss_listing: bool = False,
) -> str:
    """Build and return the markdown body for a per-run report."""
    with _connect(db_path) as conn:
        meta = _run_meta(conn, run_id)
        scores = _scores(conn, run_id)
        sections = [
            _headline(meta, scores),
            _outcome_breakdown(conn, run_id),
            _per_category(scores, conn, run_id),
            _type_miss_patterns(conn, run_id),
            _translation_errors(conn, run_id),
        ]
        if include_miss_listing:
            sections.append(_miss_listing(conn, run_id))
    return "\n".join(sections)


def write_report(
    db_path: Path | str,
    run_id: int,
    out_path: Path | str,
    *,
    include_miss_listing: bool = False,
) -> Path:
    body = render_report(db_path, run_id, include_miss_listing=include_miss_listing)
    out = Path(out_path)
    out.write_text(body)
    return out
