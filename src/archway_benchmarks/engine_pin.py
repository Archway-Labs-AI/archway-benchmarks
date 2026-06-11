"""Run the harness against a *pinned* engine commit.

A pin is a deterministic claim about a specific engine SHA ("this commit is
verified, score against it") — useful as a stable benchmark target instead of
the moving tip of a development branch. The pin file format is plain JSON:

    {"sha": "...", "tag": "...", "branch": "...", "run_id": "..."}

Where the file comes from is the caller's concern — a CI job, a verification
loop, or a manual write are all fine. This module just consumes one.

The three pieces this module owns:

  - ``read_pin`` parses the pin JSON into a ``Pin``;
  - ``ensure_pin_worktree`` materializes (idempotently) a detached git worktree
    of the engine repo at the pinned SHA — the read-only checkout the analysis
    server is then launched from;
  - ``pin_metadata`` projects the pin into the ``runs.metadata`` provenance
    shape (``engine_sha`` + pin identity) so every run is bound to the exact
    engine commit it scored.

Paths come from flags or env vars (``ARCHWAY_PIN_FILE`` / ``ARCHWAY_ENGINE_ROOT``
/ ``ARCHWAY_BENCH_PIN_WORKTREE``); the default-path constants are placeholders
that public consumers will always override.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Local-only defaults. The pin feature is opt-in via --engine-pin; in practice
# every meaningful invocation overrides these via flags or env vars (the
# defaults can't be guessed for a public consumer).
_DEFAULT_PIN_FILE = "~/.archway-benchmarks/pin/stable.json"
_DEFAULT_ENGINE_ROOT = "~/.archway-benchmarks/pin/engine"
_DEFAULT_PIN_WORKTREE = "~/.archway-benchmarks/pin/worktree"


class PinError(RuntimeError):
    """The pin could not be read or the pinned worktree could not be prepared."""


@dataclass(frozen=True)
class Pin:
    sha: str
    tag: str | None
    branch: str | None
    run_id: str | None
    source: str  # path the pin was read from
    raw: dict


# ----- defaults (env-overridable) -----

def default_pin_file() -> str:
    return os.environ.get("ARCHWAY_PIN_FILE") or os.path.expanduser(_DEFAULT_PIN_FILE)


def default_engine_root() -> str:
    return os.environ.get("ARCHWAY_ENGINE_ROOT") or os.path.expanduser(_DEFAULT_ENGINE_ROOT)


def default_pin_worktree() -> str:
    return os.environ.get("ARCHWAY_BENCH_PIN_WORKTREE") or os.path.expanduser(_DEFAULT_PIN_WORKTREE)


# ----- pin reading -----

def read_pin(pin_file: str | Path) -> Pin:
    """Parse the pin JSON. Raises ``PinError`` if absent or
    missing a usable ``sha``."""
    p = Path(pin_file).expanduser()
    if not p.exists():
        raise PinError(f"pin file not found: {p}")
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise PinError(f"could not read pin file {p}: {e}") from e
    sha = data.get("sha")
    if not sha or not isinstance(sha, str):
        raise PinError(f"pin file {p} has no usable 'sha'")
    return Pin(
        sha=sha,
        tag=data.get("tag"),
        branch=data.get("branch"),
        run_id=data.get("run_id"),
        source=str(p),
        raw=data,
    )


def pin_metadata(pin: Pin) -> dict:
    """Provenance for ``runs.metadata`` — binds a run to its engine commit.

    Mirrors the BugsInPy ``engine_sha`` convention so TypeEvalPy and BugsInPy
    runs are queryable the same way."""
    return {
        "engine_sha": pin.sha,
        "engine_pin_tag": pin.tag,
        "engine_branch": pin.branch,
        "pin_run_id": pin.run_id,
        "pin_source": pin.source,
    }


# ----- worktree materialization -----

def _git(cwd: str | Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True
    )


def _is_worktree(path: Path) -> bool:
    if not path.exists():
        return False
    r = _git(path, "rev-parse", "--is-inside-work-tree")
    return r.returncode == 0 and r.stdout.strip() == "true"


def ensure_pin_worktree(
    engine_root: str | Path, worktree: str | Path, sha: str
) -> Path:
    """Idempotently materialize a detached worktree of ``engine_root`` at ``sha``.

    Creates the worktree if absent; if it already exists as a git worktree,
    moves it to ``sha`` (a no-op when already there). The checkout is detached
    and we never write to it, so it stays clean across pins. Returns the
    worktree path. Raises ``PinError`` on any git failure or if a non-worktree
    directory is already sitting at the target path.
    """
    engine_root = Path(engine_root).expanduser()
    worktree = Path(worktree).expanduser()

    if not (engine_root / ".git").exists():
        raise PinError(f"engine_root is not a git repo: {engine_root}")

    # Make sure the pinned commit is actually present (fetch once if not).
    if _git(engine_root, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        _git(engine_root, "fetch", "--quiet", "origin")
        if _git(engine_root, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
            raise PinError(
                f"commit {sha[:12]} not found in {engine_root} (even after fetch)"
            )

    if _is_worktree(worktree):
        r = _git(worktree, "checkout", "--detach", "--quiet", sha)
        if r.returncode != 0:
            raise PinError(
                f"could not move worktree {worktree} to {sha[:12]}: {r.stderr.strip()}"
            )
    else:
        if worktree.exists() and any(worktree.iterdir()):
            raise PinError(
                f"{worktree} exists, is not a git worktree, and is non-empty; "
                "refusing to clobber"
            )
        worktree.parent.mkdir(parents=True, exist_ok=True)
        r = _git(engine_root, "worktree", "add", "--detach", "--quiet", str(worktree), sha)
        if r.returncode != 0:
            raise PinError(
                f"could not create worktree {worktree} at {sha[:12]}: {r.stderr.strip()}"
            )

    head = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    want = _git(engine_root, "rev-parse", sha).stdout.strip()
    if head != want:
        raise PinError(f"worktree {worktree} HEAD {head[:12]} != pin {want[:12]}")
    return worktree
