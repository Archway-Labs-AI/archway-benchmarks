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


def test_journal_reuses_lost_submission_and_completed_result(tmp_path):
    from archway_benchmarks.engines.hosted_sessions import SessionRunJournal
    import pytest

    calls = []
    class Client:
        def translate_analysis_artifact(self, sources, entry_module, *, request_id):
            calls.append(request_id)
            if len(calls) == 1:
                raise ConnectionError('response lost after remote acceptance')
            return {'state': 'succeeded', 'result': {'artifact_id': 'saved'}}

    path = tmp_path / 'journal.db'
    journal = SessionRunJournal(path, metadata={'engine': 'pin', 'corpus': 'pin'})
    engine = HostedSessionEngine(Client(), record=lambda _: None, journal=journal)
    with pytest.raises(ConnectionError):
        engine.translate('x = 1', 'main.py')
    journal.close()
    journal = SessionRunJournal(path, metadata={'engine': 'pin', 'corpus': 'pin'})
    engine = HostedSessionEngine(Client(), record=lambda _: None, journal=journal)
    assert engine.translate('x = 1', 'main.py')[1] == {'artifact_id': 'saved'}
    assert calls[0] == calls[1]
    assert engine.translate('x = 1', 'main.py')[1] == {'artifact_id': 'saved'}
    assert len(calls) == 2
    journal.close()
    with pytest.raises(ValueError, match='identity changed'):
        SessionRunJournal(path, metadata={'engine': 'different', 'corpus': 'pin'})


def test_journal_replays_after_completed_response_before_local_commit(tmp_path):
    from archway_benchmarks.engines.hosted_sessions import SessionRunJournal
    import pytest

    journal = SessionRunJournal(tmp_path / 'journal.db', metadata={'engine': 'pin'})
    requests = []
    def submit(request_id):
        requests.append(request_id)
        return {'state': 'succeeded', 'result': {'artifact_id': 'saved'}}
    def broken_record(event):
        if event['event'] == 'completed':
            raise OSError('local disk interrupted')
    engine = HostedSessionEngine(None, record=broken_record, journal=journal)
    with pytest.raises(OSError):
        engine._step('translate', 'case', {'source': 'x'}, submit)
    engine.record = lambda _: None
    assert engine._step('translate', 'case', {'source': 'x'}, submit) == {'artifact_id': 'saved'}
    assert requests[0] == requests[1]
    key, _, _ = journal.intent('translate', 'case', {'source': 'x'})
    with pytest.raises(ValueError, match='conflicts'):
        journal.complete(key, {'artifact_id': 'other'})
    journal.close()


def test_pycg_hosted_projection_uses_existing_name_and_frame_rules(tmp_path):
    from archway_benchmarks.pycg import PyCGCase, hosted_successor_call_edges
    from types import SimpleNamespace

    main = tmp_path / 'main.py'
    main.write_text('x = [str(i) for i in range(2)]\n')
    case = PyCGCase('macro', 'repo', tmp_path, tmp_path, main, (main,), {})
    class Engine:
        def open_program(self, sources, entry_module, *, path, options):
            assert sources == {'main': main.read_text()}
            assert entry_module == 'main'
            assert options == {'catalog_observations': False, 'possible_entry_modules': ['main']}
            return SimpleNamespace(head={})
        def command(self, result, command):
            assert command == {'kind': 'semantic_call_graph'}
            result.head = {'semantic_call_graph': {'schema': 'archway.semantic-call-graph.v1',
                'includes_capability_candidates': False, 'edges': [
                    {'caller': 'main', 'target': 'main.<listcomp>', 'evidence_grade': 'semantic'},
                    {'caller': 'main.<listcomp>', 'target': '<builtin>.str', 'evidence_grade': 'semantic'},
                ]}}
    assert hosted_successor_call_edges(case, session_engine=Engine()) == {('main', '<builtin>.str')}
