"""Produce an exact, per-observation TypyBench residual inventory.

TypyBench's CSV is intentionally aggregate.  This diagnostic runs the same
containerized extractor/scorer surface and emits the expected and predicted
Mypy types for every scored observation.  It does not alter predictions or
scoring; it makes the next analysis change attributable to a concrete residual
class instead of to a repository-wide percentage.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


_SENTINEL = "ARCHWAY_TYPYBENCH_RESIDUALS "

_CONTAINER_PROBE = r'''
import json
import os

from typybench.repo_similarity import get_repo_similarity

repo_name = os.environ["REPO"]
result = get_repo_similarity(
    f"/typybenchdata/{repo_name}/original_repo",
    f"/mnt/{repo_name}",
    base_line_repo_path=None,
)
rows = []
for key in result.score_dict:
    expected = result.a_meta_dict[key].mypy_type
    predicted_meta = result.b_meta_dict.get(key)
    rows.append({
        "key": key,
        "expected": str(expected),
        "predicted": (
            None if predicted_meta is None else str(predicted_meta.mypy_type)
        ),
        "similarity": float(result.score_dict[key]),
        "exact": int(result.exact_match_score_dict[key]),
        "missing": key in result.missing_vars,
    })
print("ARCHWAY_TYPYBENCH_RESIDUALS " + json.dumps({"rows": rows}, sort_keys=True))
'''


def observation_kind(key: str) -> str:
    if key.endswith("::return"):
        return "return"
    if "@" in key:
        return "parameter"
    return "variable"


def residual_class(row: Mapping[str, Any]) -> str:
    """Return a stable first-pass class without claiming semantic equivalence."""

    if row.get("exact"):
        return "exact"
    if row.get("missing") or row.get("predicted") is None:
        return "missing"
    expected = str(row.get("expected", ""))
    predicted = str(row.get("predicted", ""))
    if predicted == "Any":
        return "unconstrained_any"
    if "[Any" in predicted or ", Any" in predicted:
        return "erased_type_arguments"
    if float(row.get("similarity", 0.0)) == 1.0:
        return "scorer_nonexact_equivalent"
    if expected.startswith("Union[") and predicted.startswith("Union["):
        return "union_mismatch"
    return "type_mismatch"


def audit_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    audited = []
    for raw in rows:
        row = dict(raw)
        row["observation_kind"] = observation_kind(str(row["key"]))
        row["residual_class"] = residual_class(row)
        audited.append(row)
    class_counts = Counter(row["residual_class"] for row in audited)
    kind_class_counts = Counter(
        (row["observation_kind"], row["residual_class"])
        for row in audited
    )
    return {
        "schema": "archway.typybench.residual-audit.v1",
        "total_observations": len(audited),
        "class_counts": dict(sorted(class_counts.items())),
        "kind_class_counts": {
            f"{kind}:{residual}": count
            for (kind, residual), count in sorted(kind_class_counts.items())
        },
        "rows": audited,
    }


def audit_retained_residual_evidence(
    *, repo_name: str, predictions_root: Path,
) -> dict[str, Any]:
    """Audit canonical type strings retained by the official scorer."""

    evidence_path = (
        Path(predictions_root) / repo_name / f"{repo_name}_scored_keys.json"
    )
    if not evidence_path.is_file():
        raise FileNotFoundError(f"retained scorer evidence does not exist: {evidence_path}")
    payload = json.loads(evidence_path.read_text())
    if payload.get("schema") != "typybench-scored-keys-v2":
        raise ValueError(
            "retained scorer evidence lacks canonical expected/predicted types; "
            "rerun the official residual probe"
        )
    if not payload.get("type_evidence_complete"):
        raise ValueError("retained scorer type evidence is incomplete")
    return audit_rows(payload["keys"])


def run_official_residual_probe(
    *,
    repo_name: str,
    predictions_root: Path,
    image: str | None = None,
    timeout: int = 300,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Run TypyBench's installed Mypy surface and return an audited inventory."""

    predictions_root = Path(predictions_root).resolve()
    prediction = predictions_root / repo_name
    if not prediction.is_dir():
        raise FileNotFoundError(f"prediction directory does not exist: {prediction}")
    image = image or f"typybench-{repo_name.lower()}"
    with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8") as probe:
        probe.write(_CONTAINER_PROBE)
        probe.flush()
        command = [
            "docker", "run", "--rm",
            "--entrypoint", "/typybench/venv/bin/python3",
            "--mount", f"type=bind,source={predictions_root},target=/mnt,readonly",
            "--mount", f"type=bind,source={Path(probe.name).resolve()},target=/audit.py,readonly",
            image, "/audit.py",
        ]
        completed = runner(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip()
            or f"TypyBench residual probe exited {completed.returncode}"
        )
    payload = next(
        (
            line.removeprefix(_SENTINEL)
            for line in reversed(completed.stdout.splitlines())
            if line.startswith(_SENTINEL)
        ),
        None,
    )
    if payload is None:
        raise RuntimeError("TypyBench residual probe produced no residual payload")
    return audit_rows(json.loads(payload)["rows"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--predictions-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--retained-evidence",
        action="store_true",
        help="use complete v2 type evidence retained by this scorer output",
    )
    args = parser.parse_args(argv)
    if args.retained_evidence:
        result = audit_retained_residual_evidence(
            repo_name=args.repo, predictions_root=args.predictions_root,
        )
    else:
        result = run_official_residual_probe(
            repo_name=args.repo,
            predictions_root=args.predictions_root,
            image=args.image,
            timeout=args.timeout,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
