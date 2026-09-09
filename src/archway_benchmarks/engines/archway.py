"""Shared Archway translation and result contracts.

The canonical benchmark analyzer is the in-process diagram successor.  This
module retains only the source-graph translation carrier and the stable result
shape consumed by public scoring adapters; the former HTTP/monolith analyzer
has been removed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any



@dataclass(frozen=True)
class ArchwayModuleTranslation:
    module_name: str
    source: str
    path: str


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
    modules: tuple[ArchwayModuleTranslation, ...] = ()
    dependency_roots: tuple[str, ...] = ()


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

    def __init__(
        self,
        corpus_root: Path | str | None = None,
        dependency_roots: tuple[Path | str, ...] = (),
    ) -> None:
        self.corpus_root = Path(corpus_root) if corpus_root else None
        self.dependency_roots = tuple(
            str(Path(root)) for root in dependency_roots
        )

    def translate(self, source: str, path: str) -> ArchwayTranslation:
        main_path = Path(path)
        if not main_path.is_absolute() and self.corpus_root is not None:
            main_path = self.corpus_root / main_path
        modules: list[ArchwayModuleTranslation] = []
        if main_path.exists():
            root = main_path.parent
            for module_path in sorted(root.rglob("*.py")):
                relative = module_path.relative_to(root)
                if relative == Path("__init__.py"):
                    continue
                module_name = _module_name(relative)
                module_source = (
                    source if module_path == main_path
                    else module_path.read_text()
                )
                modules.append(ArchwayModuleTranslation(
                    module_name, module_source, str(module_path)
                ))
        if not modules:
            modules.append(ArchwayModuleTranslation("main", source, path))
        return ArchwayTranslation(
            source=source,
            path=path,
            modules=tuple(modules),
            dependency_roots=self.dependency_roots,
        )


def _module_name(relative: Path) -> str:
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else relative.parent.name
