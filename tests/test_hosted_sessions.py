import pytest

from archway_benchmarks.engines.hosted_sessions import HostedSessionEngine, HostedSessionResult, HostedSessionTypeEvalPyAdapter
from archway_benchmarks.types import Annotation, Location, Snippet


def test_hosted_mapping_uses_positions_and_keeps_unmapped_denominator():
    location = Location("main.py", 2, 1, "variable", "x")
    missing = Location("main.py", 3, 1, "variable", "absent")
    snippet = Snippet("typeevalpy", "case", "main.py", "", (
        Annotation(location, frozenset({"int"})), Annotation(missing, frozenset({"str"}))))
    item = {"name": "x", "kind": "variable", "module": "main", "function": None,
            "position": {"row": 2, "col": 0}, "address_id": "x", "types": ["builtins.int"]}
    result = HostedSessionResult(None, "main.py", {"observations": [item, item | {"module": "other", "types": ["builtins.str"]}]})
    assert HostedSessionTypeEvalPyAdapter().to_annotations(result, snippet) == [snippet.annotations[0]]
    assert len(snippet.annotations) == 2


def test_unresolved_catalogued_observation_demands_once_without_ground_truth():
    location = Location("main.py", 2, 1, "variable", "x")
    snippet = Snippet("typeevalpy", "case", "main.py", "", (Annotation(location, frozenset({"SECRET_EXPECTED"})),))
    item = {"name": "x", "kind": "variable", "module": "main", "function": None,
            "position": {"row": 2, "col": 0}, "address_id": "x", "types": None}

    class Engine:
        def command(self, result, command):
            assert command == {"kind": "observe_types", "address_ids": ["x"]}
            result.head = {"observations": [item | {"types": ["builtins.int"]}]}

    result = HostedSessionResult(Engine(), "main.py", {"observations": [item]})
    assert HostedSessionTypeEvalPyAdapter().to_annotations(result, snippet)[0].types == frozenset({"int"})


def test_polling_failure_preserves_operation_id_without_exception_detail():
    events = []

    class Client:
        def analysis_operation(self, operation_id, *, on_retry=None):
            raise TimeoutError("sensitive transport detail")

    engine = HostedSessionEngine(Client(), record=events.append)
    with pytest.raises(TimeoutError):
        engine._complete({"operation_id": "retained", "state": "running"}, "open", "main.py")
    assert [event["event"] for event in events] == ["accepted", "polling_failed"]
    assert events[-1]["operation"]["operation_id"] == "retained"
    assert "sensitive" not in str(events)


def test_resumed_command_must_keep_session_and_revision():
    class Client:
        def submit_analysis_command(self, *args, **kwargs):
            return {"operation_id": "operation", "state": "succeeded",
                    "result": {"session_id": "other", "revision_id": "revision"}}

    engine = HostedSessionEngine(Client(), record=lambda event: None)
    result = HostedSessionResult(engine, "main.py", {"session_id": "session", "revision_id": "revision", "checkpoint_id": "checkpoint"})
    with pytest.raises(RuntimeError, match="attribution"):
        engine.command(result, {"kind": "complete_module", "module": "main"})



def test_status_read_retry_evidence_retains_phase_and_operation(monkeypatch):
    events = []
    class Client:
        def analysis_operation(self, operation_id, *, on_retry=None):
            on_retry({"operation_id": operation_id, "attempt": 1, "status": 503, "delay_seconds": 0.25})
            return {"operation_id": operation_id, "state": "succeeded", "result": {"ok": True}}
    engine = HostedSessionEngine(Client(), record=events.append, poll_seconds=0.001)
    assert engine._complete({"operation_id": "stable", "state": "running"}, "open", "case") == {"ok": True}
    assert [e["event"] for e in events] == ["accepted", "status_read_retry", "completed"]
    assert events[1]["operation_id"] == "stable" and events[1]["phase"] == "open"
