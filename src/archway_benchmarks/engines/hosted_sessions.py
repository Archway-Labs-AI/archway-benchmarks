"""Portable session benchmark consumer; never imports the analysis engine."""

from dataclasses import dataclass
import time
from types import SimpleNamespace
from typing import Callable, Protocol
import uuid

from archway_benchmarks.engines.successor_archway import _map_observations, _typeeval_name
from archway_benchmarks.types import Annotation


class SessionClient(Protocol):
    def translate_analysis_artifact(self, sources, entry_module, *, request_id): ...
    def open_analysis_session(self, artifact_id, *, request_id, options=None): ...
    def submit_analysis_command(self, session_id, *, request_id, revision_id, checkpoint_id, command): ...
    def analysis_operation(self, operation_id): ...


@dataclass
class HostedSessionResult:
    engine: "HostedSessionEngine"
    path: str
    head: dict


class HostedSessionEngine:
    name = "archway-portable-session-diagnostic"

    def __init__(self, client: SessionClient, *, record: Callable[[dict], None],
                 deadline_seconds: float = 180, verify_resume: bool = True):
        self.client, self.record = client, record
        if deadline_seconds <= 0:
            raise ValueError("polling deadline must be positive")
        self.deadline_seconds, self.verify_resume = deadline_seconds, verify_resume

    def _complete(self, operation: dict, phase: str, path: str, *, submitted_at: float | None = None) -> dict:
        started = time.monotonic()
        polls, poll_seconds = 0, 0.0
        deadline = started + self.deadline_seconds
        self.record({"event": "accepted", "phase": phase, "path": path, "operation": operation,
                     "submission_seconds": started - submitted_at if submitted_at is not None else None})
        try:
            while operation["state"] in {"pending", "running"}:
                if time.monotonic() >= deadline:
                    raise TimeoutError("benchmark operation polling deadline exceeded")
                time.sleep(0.05)
                poll_started = time.monotonic()
                operation = self.client.analysis_operation(operation["operation_id"])
                poll_seconds += time.monotonic() - poll_started
                polls += 1
        except Exception as exc:
            self.record({"event": "polling_failed", "phase": phase, "path": path,
                         "operation": operation, "error_type": type(exc).__name__})
            raise
        self.record({"event": "completed", "phase": phase, "path": path, "operation": operation,
                     "wait_seconds": time.monotonic() - started, "poll_count": polls,
                     "poll_request_seconds": poll_seconds})
        if operation["state"] != "succeeded":
            raise RuntimeError("hosted benchmark operation failed")
        return operation["result"]

    def translate(self, source: str, path: str) -> tuple[str, dict]:
        started = time.monotonic()
        artifact = self._complete(self.client.translate_analysis_artifact(
            {"main": source}, "main", request_id=uuid.uuid4().hex), "translate", path, submitted_at=started)
        return path, artifact

    def analyze(self, translation: tuple[str, dict]) -> HostedSessionResult:
        path, artifact = translation
        started = time.monotonic()
        head = self._complete(self.client.open_analysis_session(
            artifact["artifact_id"], request_id=uuid.uuid4().hex), "open", path, submitted_at=started)
        result = HostedSessionResult(self, path, head)
        self.command(result, {"kind": "complete_module", "module": "main"})
        if self.verify_resume:
            before = result.head["observations"]
            self.command(result, {"kind": "complete_module", "module": "main"})
            if result.head["production_executions"] != 0 or result.head["observations"] != before:
                raise RuntimeError("resumed module recomputed or changed observations")
        return result

    def command(self, result: HostedSessionResult, command: dict) -> None:
        head = result.head
        started = time.monotonic()
        updated = self._complete(self.client.submit_analysis_command(head["session_id"],
            request_id=uuid.uuid4().hex, revision_id=head["revision_id"],
            checkpoint_id=head["checkpoint_id"], command=command), command["kind"], result.path, submitted_at=started)
        if (updated["session_id"], updated["revision_id"]) != (head["session_id"], head["revision_id"]):
            raise RuntimeError("hosted operation changed session/revision attribution")
        result.head = updated


class HostedSessionTypeEvalPyAdapter:
    """Reuse benchmark-owned name/span mapping over service observations.

    The initial profile covers catalogued type observations. Container-path and
    generic-shape queries are not exposed by this service profile; unmatched
    annotations remain misses in the original denominator.
    """

    def to_annotations(self, result: HostedSessionResult, snippet) -> list[Annotation]:
        demanded = set()
        for _wave in range(20):
            observations = tuple(SimpleNamespace(**(item | {
                "position": SimpleNamespace(**item["position"]) if item["position"] else None,
            })) for item in result.head["observations"] if item["module"] == "main")
            mapped = [(annotation, _map_observations(observations, annotation.location))
                      for annotation in snippet.annotations]
            missing = {item.address_id for _, candidates in mapped
                       if not any(item.types for item in candidates)
                       for item in candidates} - demanded
            if not missing:
                break
            demanded.update(missing)
            result.engine.command(result, {"kind": "observe_types", "address_ids": sorted(missing)})
        else:
            raise RuntimeError("hosted observation demand wave limit exceeded")
        return [Annotation(annotation.location, types)
                for annotation, candidates in mapped
                if (types := frozenset(_typeeval_name(value) for item in candidates for value in (item.types or [])))]
