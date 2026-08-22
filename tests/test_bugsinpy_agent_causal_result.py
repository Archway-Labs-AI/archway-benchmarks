from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark
from archway_benchmarks.bugsinpy_agent_causal_scoring import score_causal_interactions
from archway_benchmarks.bugsinpy_agent_protocol import CausalEvidenceInteraction


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "results/bugsinpy-agent-causal-calibration"


def test_published_fastapi_causal_score_is_reproducible() -> None:
    interaction = CausalEvidenceInteraction.from_json(
        json.loads((RESULT / "fastapi-1.json").read_text())
    )
    expected = json.loads((RESULT / "score.json").read_text())
    corpus = Path(os.environ.get("ARCHWAY_BUGSINPY_ROOT", ROOT / "extras/BugsInPy"))
    if not (corpus / "projects").is_dir():
        pytest.skip("BugsInPy submodule is not initialized")
    actual = score_causal_interactions(BugsInPyBenchmark(corpus), (interaction,))

    assert json.loads(json.dumps(actual)) == expected
    assert expected["interaction_count"] == 1
    assert expected["mean_delta"]["line_hit"] == 0.0
    assert expected["evidence_dispositions"] == {
        "useful": 0, "irrelevant": 1, "misleading": 0, "unusable": 0,
    }
