"""Archway engine pair — HTTP client for the local analysis dev server.

Calls Archway's ``sd_core.analysis_server`` (default ``http://localhost:8788``),
which runs ``load_package -> analyze_program -> finalize`` and returns the
``FinalizedAnalysis`` JSON for the snippet's ``main`` module.

The translation/analysis split here is mostly passthrough: the Archway server
does translation + analysis in one call, so ``ArchwayTranslationEngine`` just
bundles ``(source, path)`` and the heavy lifting happens in
``ArchwayAnalysisEngine.analyze`` (one HTTP GET per snippet). This matches the
harness Protocol shape (separate ``translate`` and ``analyze`` steps) while
letting the Archway server keep its single-call API.

Per the multi-module protocol (see ``docs/multi_module_server_protocol.md``),
we send ``GET /types?module=main.py&root=<snippet_dir>`` for every snippet —
single-file and multi-file alike. The server's ``load_package(root)`` walks
the directory, brings every sibling/submodule into scope, and analyses the
whole program so the ``main`` module's bindings reflect cross-module flow.

The opaque ``ArchwayAnalysisResult`` is consumed only by
``archway_benchmarks.benchmarks.archway_adapter.ArchwayAnalysisResultAdapter``.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_SERVER_URL = "http://localhost:8788"


@dataclass(frozen=True)
class ArchwayTranslation:
    """Passthrough — the server reads the snippet from disk via ``root``.

    ``source`` is kept on the dataclass for parity with the harness
    Protocol (other engines actually use it), but the Archway server
    doesn't read it; ``path`` is the on-disk location of ``main.py`` and
    its parent directory becomes the ``root`` query parameter.
    """

    source: str
    path: str


@dataclass(frozen=True)
class ArchwayAnalysisResult:
    """Server response for one snippet — `FinalizedAnalysis` JSON (ADR-046).

    Opaque to the harness; only ``ArchwayAnalysisResultAdapter`` reads the
    fields. ``error`` is set when the request failed or the server returned
    a 422 (translation/analysis error), so the runner can keep processing
    the rest of the corpus without an exception bubbling up.

    Shape:

    - ``module_bindings``: ``{<name>: {"element": <elt>, "source_position": ...}}``
      — module-scope names. Each entry's element is the binding's lattice type;
      ``source_position`` may be ``None`` for synthetic bindings.
    - ``functions``: list of ``FunctionView`` dicts, each with ``fn_id``,
      ``name``, ``source_position`` (the def identifier span), and
      ``instantiations`` (per call shape: ``args``, ``params``, ``captures``,
      ``locals``, ``ret`` — each non-args entry is itself a Binding dict).
      Uninstantiated functions appear with empty ``instantiations``.
    """

    snippet_path: str
    module_bindings: dict[str, dict[str, Any]] = field(default_factory=dict)
    functions: tuple[dict[str, Any], ...] = ()
    module_name: str | None = None
    error: str | None = None


class ArchwayTranslationEngine:
    name = "archway-translation"

    def translate(self, source: str, path: str) -> ArchwayTranslation:
        return ArchwayTranslation(source=source, path=path)


class ArchwayAnalysisEngine:
    """GETs the snippet's main module from the analysis dev server.

    ``corpus_root`` is the benchmark's on-disk root. Snippets carry suite-
    relative ``file_path`` (e.g. ``args/call/main.py``) so they can be used
    as join keys across the harness; here we resolve them against
    ``corpus_root`` to get the absolute path the server's ``root`` query
    param needs. If a snippet's path is already absolute it's used as-is.

    Failures (network, timeout, server-side 422 from translation/analysis
    errors, 404 for unresolvable module/root) are captured as
    ``ArchwayAnalysisResult.error`` rather than raised, so a single snippet
    that fails to translate doesn't abort the whole corpus run.
    """

    name = "archway-analysis"

    def __init__(
        self,
        server_url: str = DEFAULT_SERVER_URL,
        timeout: float = 30.0,
        corpus_root: Path | str | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self.corpus_root: Path | None = Path(corpus_root) if corpus_root else None

    def analyze(self, translation: Any) -> ArchwayAnalysisResult:
        if not isinstance(translation, ArchwayTranslation):
            raise TypeError(
                "ArchwayAnalysisEngine only consumes ArchwayTranslation; got "
                f"{type(translation).__name__}"
            )
        main_path = Path(translation.path)
        if not main_path.is_absolute() and self.corpus_root is not None:
            main_path = self.corpus_root / main_path
        snippet_dir = str(main_path.parent.resolve())
        params = urllib.parse.urlencode(
            {"module": main_path.name, "root": snippet_dir}
        )
        url = f"{self.server_url}/types?{params}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
            module = payload.get("module") or {}
            return ArchwayAnalysisResult(
                snippet_path=translation.path,
                module_bindings=module.get("bindings", {}) or {},
                functions=tuple(payload.get("functions", []) or []),
                module_name=payload.get("module_name"),
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
