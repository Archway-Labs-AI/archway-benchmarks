"""Portable session benchmark consumer; never imports the analysis engine."""

from dataclasses import dataclass
import time
import math
from types import SimpleNamespace
from typing import Callable, Protocol
import uuid
import hashlib
import json
import sqlite3

from archway_benchmarks.engines.successor_archway import _map_observations, _typeeval_name
from archway_benchmarks.types import Annotation


class SessionClient(Protocol):
    def translate_analysis_artifact(self, sources, entry_module, *, request_id): ...
    def open_analysis_session(self, artifact_id, *, request_id, options=None): ...
    def submit_analysis_command(self, session_id, *, request_id, revision_id, checkpoint_id, command): ...
    def analysis_operation(self, operation_id, *, on_retry=None): ...


class SessionRunJournal:
    """Private durable request intents and results for one pinned run.

    Intent commits before submission, so a lost response reuses the same request
    ID. Completed results are read locally. Callers pin corpus/configuration and
    service identity in metadata; credentials must never be included.
    """

    def __init__(self, path, *, metadata: dict):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS identity (singleton INTEGER PRIMARY KEY CHECK(singleton=1), metadata TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS steps (key TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, result TEXT)")
        encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO identity VALUES(1,?)", (encoded,))
        if self.db.execute("SELECT metadata FROM identity WHERE singleton=1").fetchone()[0] != encoded:
            self.db.close()
            raise ValueError("run identity changed; refusing resume")

    def intent(self, phase: str, path: str, payload: dict):
        key = hashlib.sha256(json.dumps([phase, path, payload], sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO steps VALUES(?,?,NULL)", (key, uuid.uuid4().hex))
        request_id, result = self.db.execute("SELECT request_id,result FROM steps WHERE key=?", (key,)).fetchone()
        return key, request_id, json.loads(result) if result is not None else None

    def complete(self, key: str, result: dict):
        encoded = json.dumps(result, sort_keys=True)
        with self.db:
            current = self.db.execute("SELECT result FROM steps WHERE key=?", (key,)).fetchone()
            if current is None or (current[0] is not None and current[0] != encoded):
                raise ValueError("journal result conflicts with committed step")
            self.db.execute("UPDATE steps SET result=? WHERE key=?", (encoded, key))

    def close(self):
        self.db.close()


@dataclass
class HostedSessionResult:
    engine: "HostedSessionEngine"
    path: str
    head: dict


class HostedSessionEngine:
    name = "archway-portable-session-diagnostic"

    def __init__(self, client: SessionClient, *, record: Callable[[dict], None],
                 deadline_seconds: float = 180, verify_resume: bool = True, poll_seconds: float = 0.5,
                 journal: SessionRunJournal | None = None):
        self.client, self.record, self.journal = client, record, journal
        if not math.isfinite(poll_seconds) or poll_seconds <= 0:
            raise ValueError("polling interval must be positive and finite")
        self.poll_seconds = poll_seconds
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
                time.sleep(min(self.poll_seconds, max(0, deadline - time.monotonic())))
                if time.monotonic() >= deadline:
                    raise TimeoutError("benchmark operation polling deadline exceeded")
                poll_started = time.monotonic()
                operation = self.client.analysis_operation(operation["operation_id"],
                    on_retry=lambda event: self.record({"event": "status_read_retry",
                        "phase": phase, "path": path, **event}))
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

    def _step(self, phase: str, path: str, payload: dict, submit):
        key, request_id, cached = (self.journal.intent(phase, path, payload) if self.journal
                                  else (None, uuid.uuid4().hex, None))
        if cached is not None:
            self.record({"event": "reused", "phase": phase, "path": path})
            return cached
        started = time.monotonic()
        result = self._complete(submit(request_id), phase, path, submitted_at=started)
        if self.journal:
            self.journal.complete(key, result)
        return result

    def translate(self, source: str, path: str) -> tuple[str, dict]:
        artifact = self._step("translate", path, {"sources": {"main": source}, "entry_module": "main"},
            lambda request_id: self.client.translate_analysis_artifact(
                {"main": source}, "main", request_id=request_id))
        return path, artifact

    def analyze(self, translation: tuple[str, dict]) -> HostedSessionResult:
        path, artifact = translation
        head = self._step("open", path, {"artifact_id": artifact["artifact_id"]},
            lambda request_id: self.client.open_analysis_session(artifact["artifact_id"], request_id=request_id))
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
        payload = {"session_id": head["session_id"], "revision_id": head["revision_id"],
                   "checkpoint_id": head["checkpoint_id"], "command": command}
        updated = self._step(command["kind"], result.path, payload,
            lambda request_id: self.client.submit_analysis_command(request_id=request_id, **payload))
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
