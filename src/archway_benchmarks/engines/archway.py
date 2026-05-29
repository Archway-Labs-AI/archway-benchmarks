"""Archway engine pair — HTTP client for the local analysis dev server.

Calls Archway's ``sd_core.analysis_server`` (default ``http://localhost:8788``),
which runs ``translate_module -> apply_functor(TypedMorph) -> evaluate ->
env_by_position`` and returns positioned type predictions for a single Python
snippet.

The translation/analysis split here is mostly passthrough: the Archway server
does translation + analysis in one call, so ``ArchwayTranslationEngine`` just
bundles ``(source, path)`` and the heavy lifting happens in
``ArchwayAnalysisEngine.analyze`` (one HTTP POST per snippet). This matches the
harness Protocol shape (separate ``translate`` and ``analyze`` steps) while
letting the Archway server keep its single-call API.

The opaque ``ArchwayAnalysisResult`` is consumed only by
``archway_benchmarks.benchmarks.archway_adapter.ArchwayAnalysisResultAdapter``.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_SERVER_URL = "http://localhost:8788"


@dataclass(frozen=True)
class ArchwayTranslation:
    """Passthrough — the Archway server takes source directly via POST."""

    source: str
    path: str


@dataclass(frozen=True)
class ArchwayAnalysisResult:
    """Server response for one snippet.

    Opaque to the harness; only ``ArchwayAnalysisResultAdapter`` reads
    ``positioned``. ``error`` is set when the request failed or the server
    returned a 422 (translation/analysis error), so the runner can keep
    processing the rest of the corpus without an exception bubbling up.
    """

    snippet_path: str
    positioned: tuple[dict[str, Any], ...] = ()
    error: str | None = None


class ArchwayTranslationEngine:
    name = "archway-translation"

    def translate(self, source: str, path: str) -> ArchwayTranslation:
        return ArchwayTranslation(source=source, path=path)


class ArchwayAnalysisEngine:
    """POSTs source to the analysis dev server; returns positioned results.

    Failures (network, timeout, server-side 422) are captured as
    ``ArchwayAnalysisResult.error`` rather than raised, so a single snippet
    that fails to translate doesn't abort the whole corpus run.
    """

    name = "archway-analysis"

    def __init__(self, server_url: str = DEFAULT_SERVER_URL, timeout: float = 30.0) -> None:
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout

    def analyze(self, translation: Any) -> ArchwayAnalysisResult:
        if not isinstance(translation, ArchwayTranslation):
            raise TypeError(
                "ArchwayAnalysisEngine only consumes ArchwayTranslation; got "
                f"{type(translation).__name__}"
            )
        url = f"{self.server_url}/types?name=snippet"
        req = urllib.request.Request(
            url,
            data=translation.source.encode("utf-8"),
            method="POST",
            headers={"Content-Type": "text/plain"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
            return ArchwayAnalysisResult(
                snippet_path=translation.path,
                positioned=tuple(payload.get("positioned", [])),
            )
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("error", str(e))
            except Exception:
                msg = str(e)
            return ArchwayAnalysisResult(snippet_path=translation.path, error=msg)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return ArchwayAnalysisResult(
                snippet_path=translation.path, error=f"{type(e).__name__}: {e}"
            )
