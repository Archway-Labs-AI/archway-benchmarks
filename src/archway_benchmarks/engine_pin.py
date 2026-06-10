"""Run the harness against a *pinned* engine commit.

The autonomous agent loop (the ``archway-agent-harness`` repo) verifies engine
builds and records the latest verified checkpoint to
``coordination/stable.json``:

    {"sha": "...", "tag": "stable-overnight-...", "branch": "loop/nightly-...", ...}

A pin is a deterministic claim ("this SHA is verified — no new failures vs the
prior pin"), so it's the natural stable target to benchmark against rather than
the moving, possibly-unstable tip of ``loop/main``.

This module is the seam between that pin and the harness:

  - ``read_pin`` parses ``stable.json`` into a ``Pin``;
  - ``ensure_pin_worktree`` materializes (idempotently) a detached git worktree
    of the engine repo at the pinned SHA — the read-only checkout the analysis
    server is then launched from;
  - ``pin_metadata`` projects the pin into the ``runs.metadata`` provenance
    shape (``engine_sha`` + pin identity), mirroring the BugsInPy convention so
    every run is bound to the exact engine commit it scored.

Paths default to this machine's layout but are overridable by flag or env
(``ARCHWAY_PIN_FILE`` / ``ARCHWAY_ENGINE_ROOT`` / ``ARCHWAY_BENCH_PIN_WORKTREE``)
so the same flow works on another box or in CI.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PIN_FILE = "~/Technical_Projects/archway-agent-harness/coordination/stable.json"
_DEFAULT_ENGINE_ROOT = "~/Technical_Projects/Archway"
_DEFAULT_PIN_WORKTREE = "~/Technical_Projects/Archway-worktrees/bench-pin"


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
    """Parse ``coordination/stable.json``. Raises ``PinError`` if absent or
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
