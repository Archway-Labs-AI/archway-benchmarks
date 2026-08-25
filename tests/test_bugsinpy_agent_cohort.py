from __future__ import annotations

import json
import csv
import hashlib
import re
from pathlib import Path

import pytest

from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark


ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "cohorts" / "bugsinpy-agent-pilot-v1.json"
TEST_DIRECTED_COHORT = ROOT / "cohorts" / "bugsinpy-agent-test-directed-v2.json"
CORPUS = ROOT / "extras" / "BugsInPy"


def test_agent_pilot_cohort_is_precommitted_and_resolves_exactly() -> None:
    cohort = json.loads(COHORT.read_text())
    assert cohort["schema"] == "archway.bugsinpy.agent-cohort.v1"
    assert cohort["selection"]["ground_truth_used"] is False
    assert cohort["selection"]["prior_agent_outcomes_used"] is False
    assert len(cohort["bug_keys"]) == len(set(cohort["bug_keys"])) == 12

    if not (CORPUS / "projects").is_dir():
        pytest.skip("BugsInPy submodule is not populated")
    benchmark = BugsInPyBenchmark(corpus_root=CORPUS)
    assert benchmark.corpus_commit() == cohort["corpus_revision"]
    assert {item.key for item in benchmark.subset(bug_keys=cohort["bug_keys"])} == set(
        cohort["bug_keys"]
    )


def test_agent_pilot_selection_rule_matches_declared_keys() -> None:
    cohort = json.loads(COHORT.read_text())
    assert cohort["bug_keys"] == [
        "PySnooper:1", "PySnooper:2", "PySnooper:3",
        "black:1", "black:2",
        "cookiecutter:1", "cookiecutter:2",
        "fastapi:1", "fastapi:2",
        "httpie:1", "httpie:2",
        "tqdm:1",
    ]


def test_test_directed_cohort_reconstructs_from_patch_blind_metadata() -> None:
    cohort = json.loads(TEST_DIRECTED_COHORT.read_text())
    assert cohort["protocol"] == "test-directed-static-v1"
    assert cohort["selection"]["ground_truth_used"] is False
    assert cohort["selection"]["patch_or_fix_contents_used"] is False
    assert cohort["selection"]["prior_agent_outcomes_used"] is False
    assert cohort["selection"]["calibration_cases_included"] is False
    assert len(cohort["bug_keys"]) == len(set(cohort["bug_keys"])) == 12

    projects_root = CORPUS / "projects"
    if not projects_root.is_dir():
        pytest.skip("BugsInPy submodule is not populated")
    statuses = {}
    with (projects_root / "bugsinpy-index.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            statuses.setdefault((row["repo"], row["bugid"]), {})[
                row["version"]
            ] = row["result"]
    eligible = []
    for (project, bug_id), versions in statuses.items():
        info = projects_root / project / "bugs" / bug_id / "bug.info"
        if versions != {"buggy": "fail", "fixed": "pass"} or not info.is_file():
            continue
        match = re.search(r'test_file="([^"]+)"', info.read_text(errors="replace"))
        if match and match.group(1):
            eligible.append((project, int(bug_id)))
    assert len(eligible) == cohort["selection"]["eligible_population"]["cases"]
    projects = {project for project, _ in eligible}
    assert len(projects) == cohort["selection"]["eligible_population"]["projects"]

    seed = cohort["selection"]["seed"]
    selected_projects = sorted(
        projects,
        key=lambda project: hashlib.sha256(
            f"{seed}|project|{project}".encode()
        ).hexdigest(),
    )[:12]
    selected = []
    for project in selected_projects:
        bug = min(
            (item for item in eligible if item[0] == project),
            key=lambda item: hashlib.sha256(
                f"{seed}|bug|{item[0]}:{item[1]}".encode()
            ).hexdigest(),
        )
        selected.append(f"{bug[0]}:{bug[1]}")
    assert selected == cohort["bug_keys"]

    benchmark = BugsInPyBenchmark(corpus_root=CORPUS)
    assert benchmark.corpus_commit() == cohort["corpus_revision"]
    assert {item.key for item in benchmark.subset(bug_keys=selected)} == set(selected)
