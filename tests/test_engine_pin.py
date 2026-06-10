"""Tests for the engine-pin seam (read pin + materialize detached worktree)."""
from __future__ import annotations

import json
import subprocess

import pytest

from archway_benchmarks.engine_pin import (
    Pin,
    PinError,
    default_engine_root,
    default_pin_file,
    default_pin_worktree,
    ensure_pin_worktree,
    pin_metadata,
    read_pin,
)

# ----- read_pin / pin_metadata -----

def _write(p, obj):
    p.write_text(json.dumps(obj))
    return p


def test_read_pin_parses_full_manifest(tmp_path):
    f = _write(tmp_path / "stable.json", {
        "sha": "73209ce3c5e2b7d99d87f8334ae7fefff92bd4d9",
        "tag": "stable-overnight-20260610-0255",
        "branch": "loop/nightly-20260610-0255",
        "run_id": "overnight-20260610-0255",
        "pool": 233,
    })
    pin = read_pin(f)
    assert isinstance(pin, Pin)
    assert pin.sha.startswith("73209ce3")
    assert pin.tag == "stable-overnight-20260610-0255"
    assert pin.branch == "loop/nightly-20260610-0255"
    assert pin.run_id == "overnight-20260610-0255"
    assert pin.source == str(f)
    assert pin.raw["pool"] == 233


def test_pin_metadata_shape():
    pin = Pin(sha="abc123", tag="t", branch="loop/x", run_id="r1", source="/p", raw={})
    md = pin_metadata(pin)
    assert md == {
        "engine_sha": "abc123",
        "engine_pin_tag": "t",
        "engine_branch": "loop/x",
        "pin_run_id": "r1",
        "pin_source": "/p",
    }


def test_read_pin_missing_file(tmp_path):
    with pytest.raises(PinError, match="not found"):
        read_pin(tmp_path / "nope.json")


def test_read_pin_no_sha(tmp_path):
    f = _write(tmp_path / "stable.json", {"tag": "x"})
    with pytest.raises(PinError, match="no usable 'sha'"):
        read_pin(f)


def test_read_pin_bad_json(tmp_path):
    f = tmp_path / "stable.json"
    f.write_text("{not json")
    with pytest.raises(PinError):
        read_pin(f)


def test_default_paths_env_override(monkeypatch):
    monkeypatch.setenv("ARCHWAY_PIN_FILE", "/x/pin.json")
    monkeypatch.setenv("ARCHWAY_ENGINE_ROOT", "/x/engine")
    monkeypatch.setenv("ARCHWAY_BENCH_PIN_WORKTREE", "/x/wt")
    assert default_pin_file() == "/x/pin.json"
    assert default_engine_root() == "/x/engine"
    assert default_pin_worktree() == "/x/wt"


# ----- ensure_pin_worktree (real git, in a tmp repo) -----

def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)


def _rev(cwd, ref="HEAD"):
    return subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", ref], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def two_commit_repo(tmp_path):
    repo = tmp_path / "engine"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    (repo / "a.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c1")
    sha1 = _rev(repo)
    (repo / "a.txt").write_text("two\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c2")
    sha2 = _rev(repo)
    return repo, sha1, sha2


def test_ensure_pin_worktree_creates_and_moves(two_commit_repo, tmp_path):
    repo, sha1, sha2 = two_commit_repo
    wt = tmp_path / "bench-pin"

    # Create at the older commit.
    out = ensure_pin_worktree(repo, wt, sha1)
    assert out == wt
    assert wt.is_dir()
    assert _rev(wt) == sha1
    assert (wt / "a.txt").read_text() == "one\n"

    # Idempotent: calling again at the same sha is a no-op.
    ensure_pin_worktree(repo, wt, sha1)
    assert _rev(wt) == sha1

    # Move the existing worktree to a different sha.
    ensure_pin_worktree(repo, wt, sha2)
    assert _rev(wt) == sha2
    assert (wt / "a.txt").read_text() == "two\n"


def test_ensure_pin_worktree_unknown_sha(two_commit_repo, tmp_path):
    repo, _sha1, _sha2 = two_commit_repo
    with pytest.raises(PinError, match="not found"):
        ensure_pin_worktree(repo, tmp_path / "wt", "0" * 40)


def test_ensure_pin_worktree_non_repo(tmp_path):
    with pytest.raises(PinError, match="not a git repo"):
        ensure_pin_worktree(tmp_path / "not-a-repo", tmp_path / "wt", "abc123")


def test_ensure_pin_worktree_refuses_nonempty_dir(two_commit_repo, tmp_path):
    repo, sha1, _ = two_commit_repo
    wt = tmp_path / "occupied"
    wt.mkdir()
    (wt / "stuff.txt").write_text("not a worktree")
    with pytest.raises(PinError, match="refusing to clobber"):
        ensure_pin_worktree(repo, wt, sha1)
