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
