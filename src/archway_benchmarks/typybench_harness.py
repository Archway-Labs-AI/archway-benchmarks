"""Thin wrapper for TypyBench's native annotated-source scorer.

TypyBench is a whole-repository benchmark. Its scorer consumes predicted source
trees under ``predictions/<repo>/`` and computes TypeSim/TypeCheck by running
mypy over those trees. This module deliberately does not project TypyBench into
the harness's ``Location -> type`` abstraction; it only helps callers create the
source-tree layout, build the upstream ``run.py`` invocation, and parse the CSV
that TypyBench itself writes.
"""
from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TYPYBENCH_ROOT = _REPO_ROOT / "extras" / "TypyBench" / "typybench"
DEFAULT_DATA_ROOT = _REPO_ROOT / "extras" / "TypyBench" / "typybenchdata"
DEFAULT_PREDICTIONS_ROOT = _REPO_ROOT / "extras" / "TypyBench" / "predictions"
DEFAULT_SINGLE_REPO_PREDICTIONS_ROOT = (
    _REPO_ROOT / "extras" / "TypyBench" / "predictions-single-repo"
)

REQUIRED_RESULT_COLUMNS = (
    "repo_name",
    "total_vars",
    "overall_score",
    "overall_score_wo_missing",
    "overall_score_exact",
    "overall_score_wo_missing_exact",
    "missing_ratio",
    "depth_1_score",
    "depth_2_score",
    "depth_3_score",
    "depth_4_score",
    "depth_5_score",
    "depth_1_score_exact",
    "depth_2_score_exact",
    "depth_3_score_exact",
    "depth_4_score_exact",
    "depth_5_score_exact",
    "repo_a_consistency",
    "repo_b_consistency",
    "lower_than_5_average",
    "lower_than_10_average",
    "lower_than_5_average_exact",
    "lower_than_10_average_exact",
)

NumericValue = Union[int, float, None]


@dataclass(frozen=True)
class TypyBenchResult:
    """One row from ``<repo>_results_w_exact.csv``."""

    repo_name: str
    total_vars: int
    values: dict[str, NumericValue]
    csv_path: Path

    @property
    def overall_score(self) -> Optional[float]:
        return _as_optional_float(self.values["overall_score"])

    @property
    def missing_ratio(self) -> Optional[float]:
        return _as_optional_float(self.values["missing_ratio"])

    @property
    def repo_a_consistency_errors(self) -> int:
        return int(self.values["repo_a_consistency"] or 0)

    @property
    def repo_b_consistency_errors(self) -> int:
        return int(self.values["repo_b_consistency"] or 0)


def build_command(
    *,
    typybench_root: Path = DEFAULT_TYPYBENCH_ROOT,
    data_path: Path = DEFAULT_DATA_ROOT,
    num_workers: int = 1,
    repo: Optional[str] = None,
) -> list[str]:
    """Return the official Docker image build command for TypyBench."""

    return _run_py_command(
        typybench_root=typybench_root,
        data_path=data_path,
        num_workers=num_workers,
        repo=repo,
        pred_path=None,
        build=True,
    )


def score_command(
    *,
    typybench_root: Path = DEFAULT_TYPYBENCH_ROOT,
    data_path: Path = DEFAULT_DATA_ROOT,
    pred_path: Path = DEFAULT_PREDICTIONS_ROOT,
    num_workers: int = 1,
    repo: Optional[str] = None,
) -> list[str]:
    """Return the official Docker-backed TypyBench scoring command."""

    return _run_py_command(
        typybench_root=typybench_root,
        data_path=data_path,
        num_workers=num_workers,
        repo=repo,
        pred_path=pred_path,
        build=False,
    )


def materialize_source_prediction(
    *,
    repo_name: str,
    source_root: Path,
    predictions_root: Path = DEFAULT_PREDICTIONS_ROOT,
    overwrite: bool = False,
    suffixes: Sequence[str] = (".py", ".pyi"),
) -> Path:
    """Copy source files into TypyBench's ``predictions/<repo>/`` layout.

    ``source_root`` is normally either ``typybenchdata/<repo>/repo_without_types``
    plus inserted annotations, or ``original_repo`` for a GT-vs-GT sanity run.
    Only Python source/stub files are copied; generated caches and package
    metadata are intentionally omitted.
    """

    source_root = Path(source_root)
    if not source_root.is_dir():
        raise FileNotFoundError(f"source_root does not exist: {source_root}")

    dest_root = Path(predictions_root) / repo_name
    if dest_root.exists():
        if not overwrite:
            raise FileExistsError(
                f"prediction directory already exists: {dest_root}; pass overwrite=True"
            )
        shutil.rmtree(dest_root)

    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        rel = path.relative_to(source_root)
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

    return dest_root


def ground_truth_source_root(
    repo_name: str, data_path: Path = DEFAULT_DATA_ROOT
) -> Path:
    return Path(data_path) / repo_name / "original_repo"


def untyped_source_root(repo_name: str, data_path: Path = DEFAULT_DATA_ROOT) -> Path:
    return Path(data_path) / repo_name / "repo_without_types"


def result_csv_path(
    repo_name: str, predictions_root: Path = DEFAULT_PREDICTIONS_ROOT
) -> Path:
    return Path(predictions_root) / repo_name / f"{repo_name}_results_w_exact.csv"


def stage_single_repo_prediction_root(
    *,
    repo_name: str,
    predictions_root: Path = DEFAULT_PREDICTIONS_ROOT,
    staging_root: Path = DEFAULT_SINGLE_REPO_PREDICTIONS_ROOT,
    overwrite: bool = True,
) -> Path:
    """Create a one-repo ``--pred-path`` root for bounded Docker scoring.

    Upstream ``run.py`` honors ``--repo`` when choosing available repos from the
    data path, but during scoring it still scans every directory under
    ``--pred-path``. Staging a root that contains only ``repo_name`` keeps a
    bounded single-repo run from walking all sibling predictions while preserving
    TypyBench's native Docker/scorer path.
    """

    source = Path(predictions_root) / repo_name
    if not source.is_dir():
        raise FileNotFoundError(f"prediction directory does not exist: {source}")

    staging_root = Path(staging_root)
    staged_repo = staging_root / repo_name
    if staged_repo.exists() or staged_repo.is_symlink():
        if not overwrite:
            raise FileExistsError(
                f"staged prediction directory already exists: {staged_repo}"
            )
        if staged_repo.is_dir() and not staged_repo.is_symlink():
            shutil.rmtree(staged_repo)
        else:
            staged_repo.unlink()

    staging_root.mkdir(parents=True, exist_ok=True)
    staged_repo.symlink_to(source.resolve(), target_is_directory=True)
    return staging_root


def parse_result_csv(path: Path) -> TypyBenchResult:
    """Parse a TypyBench result CSV written by upstream ``scripts/evaluation.py``."""

    path = Path(path)
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))

    if len(rows) != 1:
        raise ValueError(f"expected exactly one result row in {path}, found {len(rows)}")

    row = rows[0]
    missing = [col for col in REQUIRED_RESULT_COLUMNS if col not in row]
    if missing:
        raise ValueError(f"{path} is missing TypyBench columns: {', '.join(missing)}")

    repo_name = row["repo_name"]
    total_vars = int(row["total_vars"])
    values = {
        col: _parse_numeric_cell(row[col])
        for col in REQUIRED_RESULT_COLUMNS
        if col not in ("repo_name", "total_vars")
    }
    return TypyBenchResult(
        repo_name=repo_name,
        total_vars=total_vars,
        values=values,
        csv_path=path,
    )


def parse_results(predictions_root: Path = DEFAULT_PREDICTIONS_ROOT) -> list[TypyBenchResult]:
    """Parse all TypyBench result CSVs under a predictions root."""

    return [
        parse_result_csv(path)
        for path in sorted(Path(predictions_root).glob("*/*_results_w_exact.csv"))
    ]


def _run_py_command(
    *,
    typybench_root: Path,
    data_path: Path,
    num_workers: int,
    repo: Optional[str],
    pred_path: Optional[Path],
    build: bool,
) -> list[str]:
    cmd = [
        "python3",
        str(Path(typybench_root) / "run.py"),
        "--data-path",
        str(data_path),
        "--num-workers",
        str(num_workers),
    ]
    if build:
        cmd.append("--build")
    else:
        if pred_path is None:
            raise ValueError("pred_path is required for scoring")
        cmd.extend(["--pred-path", str(pred_path)])
    if repo is not None:
        cmd.extend(["--repo", repo])
    return cmd


def _parse_numeric_cell(value: str) -> NumericValue:
    value = value.strip()
    if value == "N/A":
        return None
    if value.isdigit():
        return int(value)
    return float(value)


def _as_optional_float(value: NumericValue) -> Optional[float]:
    if value is None:
        return None
    return float(value)
