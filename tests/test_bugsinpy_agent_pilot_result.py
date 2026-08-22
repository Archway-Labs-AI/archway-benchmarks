import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESULT = ROOT / "results/bugsinpy-agent-pilot-v1/summary.json"
ADJUDICATION = ROOT / "adjudications/bugsinpy-agent-pilot-v1-evidence.json"
COHORT = ROOT / "cohorts/bugsinpy-agent-pilot-v1.json"


def test_published_pilot_result_is_internally_consistent() -> None:
    result = json.loads(RESULT.read_text())
    cohort = json.loads(COHORT.read_text())
    adjudication = json.loads(ADJUDICATION.read_text())

    assert result["pair_count"] == len(cohort["bug_keys"]) == 12
    assert result["validity_status"] == "invalidated"
    assert result["claim"] == "excluded_prompt_condition_diagnostic_only"
    assert result["cohort_sha256"] == hashlib.sha256(COHORT.read_bytes()).hexdigest()
    assert result["post_seal_diagnostic"]["queries"] == 12
    assert sum(result["post_seal_diagnostic"]["response_status_counts"].values()) == 12
    assert result["post_seal_diagnostic"]["adjudicated_quality_counts"] == adjudication["counts"]
    assert len(adjudication["entries"]) == 12
    assert {entry["bug_key"] for entry in adjudication["entries"]} == set(cohort["bug_keys"])


def test_zero_query_pair_does_not_claim_observed_evidence_quality() -> None:
    result = json.loads(RESULT.read_text())

    assert result["conditions"]["archway_evidence_offered"]["mean_query_count"] == 0.0
    dispositions = result["paired_evidence_dispositions"]
    assert all(dispositions[label] == 0 for label in ("useful", "irrelevant", "misleading", "unusable"))
    assert "No evidence-arm agent invoked Archway" in dispositions["explanation"]
