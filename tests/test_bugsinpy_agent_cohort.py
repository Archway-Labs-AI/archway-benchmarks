from __future__ import annotations

import json
from pathlib import Path

import pytest

from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark


ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "cohorts" / "bugsinpy-agent-pilot-v1.json"
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
