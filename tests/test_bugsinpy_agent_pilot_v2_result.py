import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESULT = ROOT / "results/bugsinpy-agent-pilot-v2/summary.json"
COHORT = ROOT / "cohorts/bugsinpy-agent-pilot-v1.json"


def test_corrected_result_is_internally_consistent() -> None:
    result = json.loads(RESULT.read_text())
    cohort = json.loads(COHORT.read_text())

    assert result["pair_count"] == len(cohort["bug_keys"]) == 12
    assert result["cohort_sha256"] == hashlib.sha256(COHORT.read_bytes()).hexdigest()
    assert result["validity_status"] == "diagnostic_non_claim_grade_missing_launch_command"
    assert result["claim"] == "retained_internal_observation_working_interface_available_but_not_queried"
    audit = result["validity_audit"]
    assert audit == {
        "sealed_cases": 12, "provider_streams": 24,
        "successful_exact_wrapper_preflights": 12, "queries": 0,
        "hosted_web_search_events": 0, "issues": [],
    }
    assert sum(result["post_seal_diagnostic"]["response_status_counts"].values()) == 12
    assert result["execution_provenance"]["exact_initiating_command_retained"] is False
    assert result["execution_provenance"]["disposition"] == "not a claim-grade public baseline"


def test_zero_queries_forbid_archway_effect_claim() -> None:
    result = json.loads(RESULT.read_text())

    assert result["conditions"]["baseline"]["mean_query_count"] == 0.0
    assert result["conditions"]["archway_evidence_available"]["mean_query_count"] == 0.0
    assert any("do not estimate an Archway evidence effect" in item for item in result["claim_limitations"])
    dispositions = result["paired_evidence_dispositions"]
    assert all(dispositions[label] == 0 for label in ("useful", "irrelevant", "misleading", "unusable"))


def test_invalid_v1_remains_separate() -> None:
    prior = json.loads((ROOT / "results/bugsinpy-agent-pilot-v1/summary.json").read_text())
    current = json.loads(RESULT.read_text())

    assert prior["validity_status"] == "invalidated"
    assert current["validity_status"] != prior["validity_status"]
    assert current["private_artifact_hashes"]["run_config_sha256"] != prior["private_artifact_hashes"]["run_config_sha256"]
