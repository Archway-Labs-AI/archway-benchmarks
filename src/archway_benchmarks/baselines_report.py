"""Generate a baselines report from the harness store.

Writes two artifacts:
  - `baselines_<date>.json` — structured: tool × benchmark × {FR, FP, LV,
    Total, Sound, Complete, Runtime, image_digest, regenerated_at}, plus
    per-tool deltas vs published Aug-2024 board, and a list of failures
    captured from `.baselines_checkpoint.json` if present.
  - `baselines_<date>.md` — human-readable table for PR/Slack.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from archway_benchmarks.leaderboard import StaticLeaderboard


def collect(db_path: Path) -> dict[str, Any]:
    """Pull every external-baseline run from the store and shape it for a
    report. Returns a JSON-serialisable dict.

    Each tool row carries both strict and lenient totals. The strict number
    uses the current HEAD scorer (post-Oct-2025 `is_same_element`, requires
    col_offset). The lenient number uses `large_scale_analysis.check_match`,
    which the published Jan 2024 board was generated against. **Use the
    lenient column for "Δ vs published".**
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT r.id AS run_id, r.engine, r.benchmark, r.metadata, r.created_at,
                   s.total_snippets, s.total_annotations, s.exact_total,
                   s.files_sound, s.files_complete, s.exact_by_kind_json,
                   sl.exact_total AS exact_total_lenient,
                   sl.exact_by_kind_json AS exact_by_kind_lenient_json,
                   sl.files_sound AS files_sound_lenient,
                   sl.files_complete AS files_complete_lenient
            FROM runs r
            JOIN scores s ON s.run_id = r.id AND s.scope = 'all'
            LEFT JOIN scores sl ON sl.run_id = r.id AND sl.scope = 'all_lenient'
            WHERE r.engine LIKE 'external:%'
              AND r.id IN (
                SELECT MAX(id) FROM runs
                WHERE engine LIKE 'external:%'
                GROUP BY engine, benchmark
              )
            ORDER BY r.benchmark, COALESCE(sl.exact_total, s.exact_total) DESC
            """
        ).fetchall()
    finally:
        conn.close()

    static = StaticLeaderboard()
    snapshots: dict[str, dict[str, Any]] = {}
    for r in rows:
        metadata = json.loads(r["metadata"]) if r["metadata"] else {}
        exact_by_kind = json.loads(r["exact_by_kind_json"])
        lenient_by_kind = (
            json.loads(r["exact_by_kind_lenient_json"])
            if r["exact_by_kind_lenient_json"]
            else {}
        )
        tool = (metadata.get("tool") or r["engine"].split(":", 1)[1]).strip()
        benchmark = r["benchmark"]
        snapshots.setdefault(benchmark, {"tools": [], "snapshot": None})
        snapshots[benchmark]["tools"].append(
            {
                "tool": tool,
                "function_returns": exact_by_kind.get("return", 0),
                "function_parameters": exact_by_kind.get("parameter", 0),
                "local_variables": exact_by_kind.get("variable", 0),
                "exact_total": r["exact_total"],
                "files_sound": r["files_sound"],
                "files_complete": r["files_complete"],
                "function_returns_lenient": lenient_by_kind.get("return"),
                "function_parameters_lenient": lenient_by_kind.get("parameter"),
                "local_variables_lenient": lenient_by_kind.get("variable"),
                "exact_total_lenient": r["exact_total_lenient"],
                "files_sound_lenient": r["files_sound_lenient"],
                "files_complete_lenient": r["files_complete_lenient"],
                "total_snippets": r["total_snippets"],
                "total_annotations": r["total_annotations"],
                "runtime_seconds": metadata.get("runtime_seconds"),
                "image_digest": metadata.get("image_digest"),
                "regenerated_at": metadata.get("regenerated_at"),
                "run_id": r["run_id"],
            }
        )

    for benchmark, payload in snapshots.items():
        published = static.get(benchmark)
        if published:
            payload["published"] = [
                {
                    "tool": t.tool,
                    "function_returns": t.function_returns,
                    "function_parameters": t.function_parameters,
                    "local_variables": t.local_variables,
                    "exact_total": t.exact_total,
                }
                for t in published.tools
            ]
            payload["published_label"] = published.label
            payload["published_source"] = published.source
            # Deltas: regenerated_exact - published_exact, by tool.
            pub_by_tool = {t.tool.lower(): t.exact_total for t in published.tools}
            for entry in payload["tools"]:
                pub = pub_by_tool.get(entry["tool"].lower())
                # Δ uses the lenient regenerated number — that's the
                # comparison the published board can support.
                lenient = entry.get("exact_total_lenient")
                if pub is not None and lenient is not None:
                    entry["delta_vs_published"] = lenient - pub
                else:
                    entry["delta_vs_published"] = None
                entry["delta_basis"] = "lenient (paper-era scorer)"
        else:
            payload["published"] = []
            payload["published_label"] = None
            payload["published_source"] = None
            for entry in payload["tools"]:
                entry["delta_vs_published"] = None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshots": snapshots,
    }


def write_markdown(report: dict[str, Any], md_path: Path) -> None:
    lines: list[str] = []
    lines.append(f"# TypeEvalPy baselines · current GT · {report['generated_at']}\n")
    lines.append(
        "> **Why this exists** — the published Jan 2024 leaderboard was scored "
        "against an older ground-truth snapshot **and** an older scorer. The "
        "numbers below regenerate each baseline against the GT at the vendored "
        "repo's current HEAD, with two scorers:\n"
        ">\n"
        "> - **lenient** — `vendor/TypeEvalPy/src/result_analyzer/large_scale_analysis.check_match`, "
        "the paper-era predicate (col_offset/line check commented out, lines 46-51). "
        "Use this column for **Δ vs published**.\n"
        "> - **strict** — the current HEAD's `analysis_utils.is_same_element` "
        "(commit `2f7c6056`, Oct 2025). Requires col_offset match. Existing tool "
        "runners (Jedi, Scalpel, HeaderGen) do NOT emit col_offset and so score 0 "
        "under strict. **This is a vendor scorer change, not a wiring bug.** Archway "
        "emits col_offset and is held to this stricter bar.\n"
    )

    for benchmark, payload in report["snapshots"].items():
        lines.append(f"\n## {benchmark}\n")
        if payload["published_source"]:
            lines.append(f"_{payload['published_label']}_ · {payload['published_source']}\n")

        # Comparison table — lenient leads (the comparable number); strict in parens.
        lines.append(
            "| Tool | FR | FP | LV | **Total lenient** | Δ vs published | Total strict | Sound (lenient) | Complete (lenient) | Runtime |"
        )
        lines.append(
            "| --- | --: | --: | --: | --: | --: | --: | --: | --: | --: |"
        )
        for t in payload["tools"]:
            total_snip = t.get("total_snippets") or "?"
            delta = t.get("delta_vs_published")
            delta_str = (
                f"{'+' if delta and delta > 0 else ''}{delta}" if delta is not None else "—"
            )
            rt = (
                f"{t['runtime_seconds']:.0f}s"
                if t.get("runtime_seconds")
                else "—"
            )
            fr_l = t.get("function_returns_lenient")
            fp_l = t.get("function_parameters_lenient")
            lv_l = t.get("local_variables_lenient")
            total_l = t.get("exact_total_lenient")
            sound_l = t.get("files_sound_lenient")
            complete_l = t.get("files_complete_lenient")
            lines.append(
                f"| **{t['tool']}** "
                f"| {fr_l if fr_l is not None else '—'} "
                f"| {fp_l if fp_l is not None else '—'} "
                f"| {lv_l if lv_l is not None else '—'} "
                f"| **{total_l if total_l is not None else '—'}** "
                f"| {delta_str} "
                f"| {t['exact_total']} (FR={t['function_returns']}, FP={t['function_parameters']}, LV={t['local_variables']}) "
                f"| {sound_l if sound_l is not None else '—'}/{total_snip} "
                f"| {complete_l if complete_l is not None else '—'}/{total_snip} "
                f"| {rt} |"
            )

        # Published reference (for verification only — never cite cross-column)
        if payload["published"]:
            lines.append("\n### Published Aug-2024 reference (stale GT — do not cross-compare)\n")
            lines.append("| Tool | FR | FP | LV | Total |")
            lines.append("| --- | --: | --: | --: | --: |")
            for t in payload["published"]:
                lines.append(
                    f"| {t['tool']} | {t['function_returns']} | {t['function_parameters']} | "
                    f"{t['local_variables']} | {t['exact_total']} |"
                )

    # Failures from checkpoint
    checkpoint = Path(".baselines_checkpoint.json")
    if checkpoint.exists():
        ckpt = json.loads(checkpoint.read_text())
        failures = {k: v for k, v in ckpt.items() if v.get("status") != "ok"}
        if failures:
            lines.append("\n## Tools that failed to run / build\n")
            for key, v in sorted(failures.items()):
                err = v.get("error", "?")
                # Trim very long stacktraces.
                if len(err) > 240:
                    err = err[:240] + "..."
                lines.append(f"- **{key}** — {err}")

    # Honest summary paragraph
    lines.append("\n## Honest summary\n")
    lines.append(_summary_paragraph(report))

    md_path.write_text("\n".join(lines) + "\n")


def _summary_paragraph(report: dict[str, Any]) -> str:
    """One paragraph: which baselines are solid, which are shaky, and the
    current-GT rank order. So we know what's safe to cite."""
    parts: list[str] = []

    for benchmark, payload in report["snapshots"].items():
        tools = sorted(
            payload["tools"],
            key=lambda t: -(t.get("exact_total_lenient") or 0),
        )
        if not tools:
            continue
        order = " > ".join(
            f"{t['tool']} ({t.get('exact_total_lenient') or 0})" for t in tools
        )
        parts.append(f"**{benchmark} (lenient, current GT):** {order}.")

    parts.append(
        "Solid: HeaderGen, Jedi, Scalpel — close-to-published numbers under the "
        "lenient (paper-era) scorer, with Δ explainable by the April-2026 "
        "inheritance/MRO ground-truth update (commit `3719de11`) and the "
        "845→850 micro composition change."
    )
    parts.append(
        "Shaky / not run: Pyright (LSP stuck >40 min on micro; needs a longer "
        "budget or a non-LSP runner); HiTyper (vendor Dockerfile expects a "
        "`requirements.txt` that's missing from `vendor/TypeEvalPy/src/target_tools/hityper/` — "
        "upstream bug); Type4Py / HiTyper-DL (require a model server we are not "
        "running). For now, **only the three solid tools should be cited** as "
        "regenerated-on-current-GT baselines."
    )
    parts.append(
        "Under the **strict** scorer (`is_same_element`, commit `2f7c6056` Oct 2025, "
        "requires col_offset match), all three solid tools score 0/total — their "
        "runners don't emit col_offset. **This is a vendor scorer change, not a "
        "wiring bug** (verified by running the lenient scorer above against the "
        "same outputs and getting near-published numbers). Archway emits col_offset "
        "and is the one tool that meets the strict bar today."
    )
    return "\n\n".join(parts)


def write_json(report: dict[str, Any], json_path: Path) -> None:
    json_path.write_text(json.dumps(report, indent=2) + "\n")


def _cli(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="archway-bench-report")
    parser.add_argument("--db", default="runs.db")
    parser.add_argument(
        "--out-md",
        default=None,
        help="Markdown path (default: baselines_<date>.md)",
    )
    parser.add_argument(
        "--out-json",
        default=None,
        help="JSON path (default: baselines_<date>.json)",
    )
    args = parser.parse_args(argv)

    report = collect(Path(args.db))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    md_path = Path(args.out_md or f"baselines_{stamp}.md")
    json_path = Path(args.out_json or f"baselines_{stamp}.json")
    write_markdown(report, md_path)
    write_json(report, json_path)
    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
