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
    report. Returns a JSON-serialisable dict."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT r.id AS run_id, r.engine, r.benchmark, r.metadata, r.created_at,
                   s.total_snippets, s.total_annotations, s.exact_total,
                   s.files_sound, s.files_complete, s.exact_by_kind_json
            FROM runs r
            JOIN scores s ON s.run_id = r.id AND s.scope = 'all'
            WHERE r.engine LIKE 'external:%'
              AND r.id IN (
                SELECT MAX(id) FROM runs
                WHERE engine LIKE 'external:%'
                GROUP BY engine, benchmark
              )
            ORDER BY r.benchmark, s.exact_total DESC
            """
        ).fetchall()
    finally:
        conn.close()

    static = StaticLeaderboard()
    snapshots: dict[str, dict[str, Any]] = {}
    for r in rows:
        metadata = json.loads(r["metadata"]) if r["metadata"] else {}
        exact_by_kind = json.loads(r["exact_by_kind_json"])
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
                entry["delta_vs_published"] = (
                    entry["exact_total"] - pub if pub is not None else None
                )
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
        "> **Why this exists** — the published Aug-2024 leaderboard was scored "
        "against an older ground-truth snapshot. The numbers below regenerate "
        "each baseline against the GT at the vendored repo's current HEAD, so "
        "head-to-head with our analysis is honest.\n"
    )

    for benchmark, payload in report["snapshots"].items():
        lines.append(f"\n## {benchmark}\n")
        if payload["published_source"]:
            lines.append(f"_{payload['published_label']}_ · {payload['published_source']}\n")

        # Comparison table
        lines.append(
            "| Tool | FR | FP | LV | **Total (current GT)** | Δ vs published | Sound | Complete | Runtime |"
        )
        lines.append(
            "| --- | --: | --: | --: | --: | --: | --: | --: | --: |"
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
            lines.append(
                f"| **{t['tool']}** | {t['function_returns']} | {t['function_parameters']} | "
                f"{t['local_variables']} | **{t['exact_total']}** | {delta_str} | "
                f"{t['files_sound']}/{total_snip} | {t['files_complete']}/{total_snip} | {rt} |"
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
            for key, v in failures.items():
                err = v.get("error", "?")
                # Trim very long stacktraces.
                if len(err) > 240:
                    err = err[:240] + "..."
                lines.append(f"- **{key}** — {err}")

    md_path.write_text("\n".join(lines) + "\n")


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
