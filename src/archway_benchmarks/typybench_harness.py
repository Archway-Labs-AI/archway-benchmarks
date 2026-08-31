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
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_TYPYBENCH_ROOT = _REPO_ROOT / ".archway-benchmarks" / "typybench"
DEFAULT_TYPYBENCH_ROOT = _REPO_ROOT / "extras" / "TypyBench"
DEFAULT_DATA_ROOT = _LOCAL_TYPYBENCH_ROOT / "data" / "typybenchdata"
DEFAULT_PREDICTIONS_ROOT = _LOCAL_TYPYBENCH_ROOT / "runs" / "predictions"
DEFAULT_SINGLE_REPO_PREDICTIONS_ROOT = (
    _LOCAL_TYPYBENCH_ROOT / "runs" / "predictions-single-repo"
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


@dataclass(frozen=True)
class TypyBenchScoredKeys:
    """Exact key-level result exported by the native TypyBench scorer."""

    repo_name: str
    keys: tuple[dict[str, object], ...]
    path: Path

    @property
    def missing_count(self) -> int:
        return sum(bool(item.get("missing")) for item in self.keys)


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
    progress_jsonl: Optional[Path] = None,
    log_dir: Optional[Path] = None,
    skip_completed: bool = False,
) -> list[str]:
    """Return the official Docker-backed TypyBench scoring command."""

    return _run_py_command(
        typybench_root=typybench_root,
        data_path=data_path,
        num_workers=num_workers,
        repo=repo,
        pred_path=pred_path,
        build=False,
        progress_jsonl=progress_jsonl,
        log_dir=log_dir,
        skip_completed=skip_completed,
    )


def available_repos(data_path: Path = DEFAULT_DATA_ROOT) -> list[str]:
    """Return TypyBench repo names available under ``typybenchdata``."""

    data_path = Path(data_path)
    if not data_path.is_dir():
        raise FileNotFoundError(f"TypyBench data path does not exist: {data_path}")
    return sorted(
        path.name
        for path in data_path.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )


def docker_image_name(repo_name: str) -> str:
    """Return TypyBench's native Docker image tag for ``repo_name``."""

    return f"typybench-{repo_name.lower()}"


def local_docker_images(
    *,
    docker_cmd: Sequence[str] = ("docker",),
    prefix: str = "typybench-",
) -> set[str]:
    """Return locally available Docker image repositories for TypyBench.

    This is a read-only preflight helper. It deliberately reports repository
    names without tags because TypyBench's ``run.py`` invokes images by bare
    repository name, relying on Docker's default ``latest`` tag.
    """

    proc = subprocess.run(
        [
            *docker_cmd,
            "images",
            "--format",
            "{{.Repository}}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "docker images failed")
    return {
        line.strip()
        for line in proc.stdout.splitlines()
        if line.strip().startswith(prefix)
    }


def missing_docker_images(
    *,
    data_path: Path = DEFAULT_DATA_ROOT,
    local_images: set[str] | None = None,
    docker_cmd: Sequence[str] = ("docker",),
) -> list[str]:
    """Return repo names whose native TypyBench image is missing locally."""

    repos = available_repos(data_path)
    images = local_images if local_images is not None else local_docker_images(
        docker_cmd=docker_cmd
    )
    return [repo for repo in repos if docker_image_name(repo) not in images]


def python_source_files(
    source_root: Path,
    *,
    suffixes: Sequence[str] = (".py",),
) -> list[Path]:
    """Return Python source files under ``source_root`` in stable order."""

    source_root = Path(source_root)
    if not source_root.is_dir():
        raise FileNotFoundError(f"source root does not exist: {source_root}")
    suffix_set = set(suffixes)
    return sorted(
        path
        for path in source_root.rglob("*")
        if path.is_file() and path.suffix in suffix_set
    )


def require_python_source_files(
    source_root: Path,
    *,
    label: str = "source root",
    suffixes: Sequence[str] = (".py",),
) -> list[Path]:
    """Return source files, failing clearly when a benchmark fixture is empty."""

    files = python_source_files(source_root, suffixes=suffixes)
    if not files:
        suffix_list = ", ".join(suffixes)
        raise ValueError(
            f"{label} contains no Python source files ({suffix_list}): {Path(source_root)}"
        )
    return files


def validate_repo_source_trees(
    repo_name: str,
    *,
    data_path: Path = DEFAULT_DATA_ROOT,
    tree_names: Sequence[str] = ("repo_without_types", "original_repo"),
) -> dict[str, int]:
    """Validate that a TypyBench repo fixture has Python files in required trees."""

    counts: dict[str, int] = {}
    for tree_name in tree_names:
        root = Path(data_path) / repo_name / tree_name
        files = require_python_source_files(
            root,
            label=f"TypyBench repo {repo_name!r} {tree_name}",
            suffixes=(".py",),
        )
        counts[tree_name] = len(files)
    return counts


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
    files = require_python_source_files(
        source_root,
        label="source_root",
        suffixes=suffixes,
    )

    dest_root = Path(predictions_root) / repo_name
    if dest_root.exists():
        if not overwrite:
            raise FileExistsError(
                f"prediction directory already exists: {dest_root}; pass overwrite=True"
            )
        shutil.rmtree(dest_root)

    for path in files:
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


def scored_keys_path(
    repo_name: str, predictions_root: Path = DEFAULT_PREDICTIONS_ROOT
) -> Path:
    return Path(predictions_root) / repo_name / f"{repo_name}_scored_keys.json"


def parse_scored_keys(
    repo_name: str, predictions_root: Path = DEFAULT_PREDICTIONS_ROOT
) -> TypyBenchScoredKeys:
    path = scored_keys_path(repo_name, predictions_root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "typybench-scored-keys-v1":
        raise ValueError(f"unsupported TypyBench scored-key schema: {path}")
    keys = tuple(payload.get("keys") or ())
    if payload.get("count") != len(keys):
        raise ValueError(f"invalid TypyBench scored-key count: {path}")
    return TypyBenchScoredKeys(
        repo_name=str(payload["repo_name"]),
        keys=keys,
        path=path,
    )


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
    require_python_source_files(
        source,
        label=f"prediction directory for TypyBench repo {repo_name!r}",
        suffixes=(".py", ".pyi"),
    )

    staging_root = Path(staging_root)
    # Older scorer layouts used ``staging_root/<repo>`` directly and may leave
    # that path as a symlink to the prediction tree. A newer per-repository
    # staging root must never traverse such a symlink: doing so can mistake a
    # real source package for staging state and delete it. Replace only the
    # staging-root symlink itself before creating the isolated directory.
    if staging_root.is_symlink():
        staging_root.unlink()
    elif staging_root.exists() and not staging_root.is_dir():
        raise NotADirectoryError(f"staging root is not a directory: {staging_root}")
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
    progress_jsonl: Optional[Path] = None,
    log_dir: Optional[Path] = None,
    skip_completed: bool = False,
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
        if progress_jsonl is not None:
            cmd.extend(["--progress-jsonl", str(progress_jsonl)])
        if log_dir is not None:
            cmd.extend(["--log-dir", str(log_dir)])
        if skip_completed:
            cmd.append("--skip-completed")
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
