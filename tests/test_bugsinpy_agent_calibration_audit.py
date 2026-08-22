from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pilot_oracle_audit_covers_exact_precommitted_cohort() -> None:
    cohort = json.loads((ROOT / "cohorts/bugsinpy-agent-pilot-v1.json").read_text())
    audit = json.loads((
        ROOT / "calibrations/bugsinpy-agent-evidence/pilot-v1-oracle-eligibility-audit.json"
    ).read_text())

    assert audit["schema"] == "archway.bugsinpy.agent-evidence-calibration-audit.v1"
    assert audit["corpus_revision"] == cohort["corpus_revision"]
    assert audit["oracle_used"] is True
    assert audit["calibration_only"] is True
    assert audit["detector_received_oracle"] is False
    assert [case["bug_key"] for case in audit["cases"]] == cohort["bug_keys"]
    assert audit["eligible_cases"] == 0
    assert audit["decision"] == "do_not_launch_agent_on_this_cohort"
    assert all(case["technical_status"] for case in audit["cases"])


def test_fastapi_calibration_search_is_ordered_and_stops_without_agent() -> None:
    search = json.loads((
        ROOT / "calibrations/bugsinpy-agent-evidence/fastapi-numeric-call-argument-search.json"
    ).read_text())

    assert search["schema"] == "archway.bugsinpy.agent-evidence-calibration-search.v1"
    assert search["calibration_only"] is True
    assert search["detector_received_oracle"] is False
    assert [case["bug_key"] for case in search["candidates"]] == [
        f"fastapi:{bug_id}" for bug_id in range(3, 17)
    ]
    assert [case["bug_key"] for case in search["candidates"] if case["decision"] == "probe"] == [
        "fastapi:9", "fastapi:13", "fastapi:16",
    ]
    assert search["eligible_cases"] == 0
    assert search["decision"].startswith("fastapi_search_exhausted_without_an_eligible_case")


def test_post_fastapi_search_obeys_precommitted_probe_limit() -> None:
    search = json.loads((
        ROOT / "calibrations/bugsinpy-agent-evidence/post-fastapi-call-argument-search.json"
    ).read_text())

    assert search["schema"] == "archway.bugsinpy.agent-evidence-calibration-search.v1"
    assert search["calibration_only"] is True
    assert search["detector_received_oracle"] is False
    assert search["project_order"][:2] == ["httpie", "keras"]
    probes = [case for case in search["candidates"] if case["decision"] == "probe"]
    assert [case["bug_key"] for case in probes] == ["keras:4", "keras:7", "keras:15"]
    assert all(case["result"] in {"not_collected", "unsupported"} for case in probes)
    assert search["qualifying_probes_run"] == search["maximum_probe_candidates"] == 3
    assert search["eligible_cases"] == 0
    assert search["status"] == "stopped_at_precommitted_probe_limit"
    assert search["decision"].startswith("do_not_launch_agent")


def test_possible_calls_search_pauses_on_unbounded_tool_failure() -> None:
    search = json.loads((
        ROOT / "calibrations/bugsinpy-agent-evidence/possible-calls-search-v1.json"
    ).read_text())

    assert search["query_kind"] == "possible-calls"
    assert search["calibration_only"] is True
    assert search["detector_received_oracle"] is False
    assert [case["bug_key"] for case in search["candidates"]] == [
        "keras:16", "keras:17",
    ]
    probe = search["candidates"][1]
    assert probe["decision"] == "probe"
    assert probe["result"] == "tool_error"
    assert search["qualifying_probes_attempted"] == 1
    assert search["bounded_probe_results"] == search["eligible_cases"] == 0
    assert search["status"] == "paused_on_engine_serialization_handoff"
    assert search["decision"].startswith("do_not_launch_agent")
