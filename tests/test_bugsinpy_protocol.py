from __future__ import annotations

import pytest

from archway_benchmarks.bugsinpy_protocol import (
    DETECTOR_INPUT_SCHEMA,
    DetectorInputManifest,
    ProtocolViolation,
    RankedFinding,
    RankedPredictionBundle,
)


def _input(**updates):
    value = {
        "schema": DETECTOR_INPUT_SCHEMA,
        "protocol": "repository-static-v1",
        "bug_key": "demo:1",
        "project": "demo",
        "buggy_revision": "a" * 40,
        "repository_root": "/isolated/buggy-checkout",
        "entrypoints": [],
    }
    value.update(updates)
    return value


@pytest.mark.parametrize(
    "field",
    ["patch", "fixed_source", "files_touched", "bug_locations", "ground_truth", "bug_class"],
)
def test_detector_input_rejects_hidden_evaluator_fields(field):
    value = _input()
    value[field] = "leak"
    with pytest.raises(ProtocolViolation, match="forbidden detector-input field"):
        DetectorInputManifest.from_json(value)


def test_detector_input_rejects_nested_hidden_evaluator_fields():
    value = _input(entrypoints=[{"name": "test_x", "fixed_commit": "leak"}])
    with pytest.raises(ProtocolViolation, match="forbidden detector-input field"):
        DetectorInputManifest.from_json(value)


def test_repository_static_forbids_test_entrypoints():
    with pytest.raises(ProtocolViolation, match="cannot receive test entrypoints"):
        DetectorInputManifest.from_json(_input(entrypoints=["tests/test_demo.py::test_x"]))


def test_test_directed_requires_entrypoint_and_round_trips():
    value = _input(
        protocol="test-directed-static-v1",
        entrypoints=["tests/test_demo.py::test_x"],
    )
    manifest = DetectorInputManifest.from_json(value)
    assert manifest.to_json() == value


def test_ranked_prediction_requires_contiguous_ranks_and_valid_coverage():
    finding = RankedFinding(2, "demo.py", 10, 10, "exception-path")
    with pytest.raises(ProtocolViolation, match="contiguous"):
        RankedPredictionBundle(
            protocol="repository-static-v1",
            bug_key="demo:1",
            buggy_revision="a" * 40,
            findings=(finding,),
            repository_files=1,
            repository_loc=20,
            analyzed_files=1,
            analyzed_loc=20,
        )


def test_ranked_prediction_json_round_trip():
    prediction = RankedPredictionBundle(
        protocol="repository-static-v1",
        bug_key="demo:1",
        buggy_revision="a" * 40,
        findings=(RankedFinding(1, "demo.py", 10, 11, "exception-path", 0.75),),
        repository_files=2,
        repository_loc=40,
        analyzed_files=2,
        analyzed_loc=40,
    )
    assert RankedPredictionBundle.from_json(prediction.to_json()) == prediction


def test_ranked_prediction_rejects_ground_truth_leak_in_evidence():
    prediction = RankedPredictionBundle(
        protocol="repository-static-v1",
        bug_key="demo:1",
        buggy_revision="a" * 40,
        findings=(
            RankedFinding(
                1,
                "demo.py",
                10,
                10,
                "exception-path",
                evidence=({"fixed_source_comparison": "changed"},),
            ),
        ),
        repository_files=1,
        repository_loc=20,
        analyzed_files=1,
        analyzed_loc=20,
    )
    with pytest.raises(ProtocolViolation, match="forbidden detector-input field"):
        RankedPredictionBundle.from_json(prediction.to_json())


def test_ranked_prediction_rejects_duplicate_source_spans():
    repeated = (
        RankedFinding(1, "demo.py", 10, 10, "one"),
        RankedFinding(2, "demo.py", 10, 10, "two"),
    )
    with pytest.raises(ProtocolViolation, match="repeat the same source span"):
        RankedPredictionBundle(
            protocol="repository-static-v1",
            bug_key="demo:1",
            buggy_revision="a" * 40,
            findings=repeated,
            repository_files=1,
            repository_loc=20,
            analyzed_files=1,
            analyzed_loc=20,
        )
