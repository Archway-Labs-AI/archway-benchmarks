"""Manifest-status laws for the checkpointable successor corpus runner."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace


_SCRIPT = Path(__file__).parents[1] / "scripts" / "typybench_successor_run.py"
_SPEC = spec_from_file_location("typybench_successor_run", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_RUNNER = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RUNNER)


def _stats(summary):
    return SimpleNamespace(
        file_profiles=[SimpleNamespace(analysis_summary=summary)],
        failures=(),
        files_total=1,
        files_analyzed=1,
        files_failed=0,
        functions_seen=1,
        functions_annotated=1,
        params_annotated=1,
        returns_annotated=1,
        variables_annotated=0,
    )


def test_analysis_timeout_is_not_mislabeled_complete() -> None:
    record = _RUNNER._stats_record(
        _stats({
            "timed_out_body": True,
            "timed_out_execution": {
                "active_family": "CallableSummaryApplication",
            },
        }),
        25.0,
    )

    assert record["status"] == "timed_out"
    assert record["analysis_summary"]["timed_out_execution"] == {
        "active_family": "CallableSummaryApplication",
    }


def test_complete_analysis_remains_complete() -> None:
    record = _RUNNER._stats_record(
        _stats({"timed_out_body": False}), 5.0
    )

    assert record["status"] == "complete"
