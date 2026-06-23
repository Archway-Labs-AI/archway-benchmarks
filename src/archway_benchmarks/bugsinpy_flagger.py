"""BugsInPy DETECTION flagger — drives Archway's OWN analysis as the flagger.

This is the honest, attributable detection path for Track 1. It does NOT score
or classify; it produces the `flagged.json` that `archway-bench bugsinpy-detect`
joins against each bug's patch-derived ground-truth lines.

Pipeline (two subcommands so the slow engine step is run + monitored on its own):

  1. `fetch`  — for every bug, fetch the BUGGY version of each patch-touched `.py`
                file straight from GitHub raw at the bug's `buggy_commit`
                (lightweight: just the touched files, no full checkout). Writes a
                MANIFEST mapping each bug to its on-disk fetched files + fetch status.

  2. (engine) — run `scripts/bugsinpy_analyze_driver.py` under the PINNED engine's
                hatch env (cwd = read-only worktree) over the manifest. It is the
                ONLY step that touches the engine, and it is read-only.

  3. `build-flags` — join the manifest with the driver's per-file results into
                `flagged.json` ({bug_key: [{file, lines}]}) — the engine's
                `bottom`-element rows are the flags — plus a `status.json` sidecar
                giving the per-file load/analyze breakdown (the coverage weakness).

The flag predicate (a `bottom` lattice element at a source row) lives in the
driver and is documented there. Here we only move bytes and shape JSON.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from archway_benchmarks.benchmarks.bugsinpy import BugsInPyBenchmark


# ----- GitHub raw fetch -----

def _owner_repo(github_url: str) -> tuple[str, str] | None:
    s = (github_url or "").strip().rstrip("/")
    for pre in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if s.startswith(pre):
            s = s[len(pre):]
            break
    if s.endswith(".git"):
        s = s[:-4]
    parts = [p for p in s.split("/") if p]
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def _raw_url(owner: str, repo: str, commit: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{commit}/{path}"


def _flat(path: str) -> str:
    return path.replace("/", "__")


# ----- short-SHA recovery -----
#
# Some bugs (all of pandas, in the vendored corpus) record a 7-char abbreviated
# `buggy_commit_id`. On a repo pandas's size a 7-char prefix is sometimes
# AMBIGUOUS, so `raw.githubusercontent.com/<repo>/<7sha>/<path>` 404s (GitHub
# refuses to resolve the ambiguous ref). The full 40-char SHA always resolves.
# We recover it from the FIXED commit's parent: in BugsInPy the buggy commit is
# the parent of the fix, and we only accept the parent when it actually starts
# with the recorded short SHA (a verifiable guarantee we fetched the intended
# commit — never a guess). This is purely a loading fix; it touches no engine.
_sha_cache: dict[str, str | None] = {}
_sha_lock = threading.Lock()
_sha_cache_loaded = False
# Persisted so the (rate-limited, 60/hr unauthenticated) GitHub API resolution is
# paid AT MOST ONCE EVER per short SHA, even across separate runs/processes.
_SHA_CACHE_PATH = Path(
    __import__("os").environ.get(
        "BUGSINPY_SHA_CACHE",
        str(Path.home() / ".cache" / "archway_benchmarks" / "bugsinpy_sha_resolution.json")))


def _load_sha_cache() -> None:
    global _sha_cache_loaded
    if _sha_cache_loaded:
        return
    try:
        disk = json.loads(_SHA_CACHE_PATH.read_text())
        if isinstance(disk, dict):
            _sha_cache.update({k: v for k, v in disk.items() if v})  # keep only resolved
    except (OSError, json.JSONDecodeError):
        pass
    _sha_cache_loaded = True


def _save_sha_cache() -> None:
    try:
        _SHA_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SHA_CACHE_PATH.write_text(json.dumps(
            {k: v for k, v in _sha_cache.items() if v}, indent=2, sort_keys=True))
    except OSError:
        pass


def _resolve_full_sha(owner: str, repo: str, short_sha: str, fixed_sha: str) -> str | None:
    """Expand an abbreviated `short_sha` to its full 40-char form via the fixed
    commit's parent. Returns the full SHA only if it prefix-matches `short_sha`
    (otherwise None — we refuse to fetch a commit we can't verify is the one
    recorded). Cached per (owner/repo, short_sha), persisted to disk; network
    only on the first-ever miss for a given short SHA."""
    if not fixed_sha:
        return None
    ck = f"{owner}/{repo}@{short_sha}"
    with _sha_lock:
        _load_sha_cache()
        if ck in _sha_cache:
            return _sha_cache[ck]
    parent = None
    try:
        proc = subprocess.run(
            ["curl", "-sS", "--max-time", "30",
             f"https://api.github.com/repos/{owner}/{repo}/commits/{fixed_sha}"],
            capture_output=True, text=True, timeout=40)
        data = json.loads(proc.stdout or "{}")
        cand = (data.get("parents") or [{}])[0].get("sha")
        if cand and cand.startswith(short_sha):  # verifiable match — not a guess
            parent = cand
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError, KeyError):
        parent = None
    with _sha_lock:
        _sha_cache[ck] = parent
        if parent:
            _save_sha_cache()
    return parent


def _fetch_one(url: str, dest: Path, timeout: float = 25.0) -> str:
    """Return a status string; writes `dest` on success. Cached if dest exists.

    Shells out to `curl` (the benchmarks venv's Python lacks a usable CA bundle,
    so urllib HTTPS fails cert verification; curl uses the system trust store).
    """
    if dest.exists() and dest.stat().st_size > 0:
        return "cached"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            ["curl", "-sS", "-L", "--max-time", str(int(timeout)),
             "-w", "%{http_code}", "-o", str(dest), url],
            capture_output=True, text=True, timeout=timeout + 10)
    except (OSError, subprocess.SubprocessError) as e:
        dest.unlink(missing_ok=True)
        return f"curlerr:{type(e).__name__}"
    if proc.returncode != 0:  # transport error (timeout, DNS, reset)
        dest.unlink(missing_ok=True)
        return f"curlerr:{proc.returncode}"
    code = (proc.stdout or "").strip()[-3:]
    if code == "200":
        return "ok"
    dest.unlink(missing_ok=True)  # curl wrote the error body; discard it
    return f"http_{code}"


def build_manifest(bench: BugsInPyBenchmark, cache_dir: Path, *,
                   projects: list[str] | None = None, limit: int | None = None,
                   workers: int = 8) -> tuple[list[dict], Counter]:
    """Fetch every bug's patch-touched .py files at its buggy commit.

    Returns (manifest, fetch_status_counter). A bug with NO github url or NO
    .py touched files still appears (with empty/failed files) so the denominator
    stays the full attempted set.
    """
    bugs = bench.load()
    if projects:
        allow = set(projects)
        bugs = [b for b in bugs if b.project in allow]
    if limit:
        bugs = bugs[:limit]

    # Flatten to fetch jobs carrying enough context to recover a 404 via the
    # full SHA: (key, repo_path, owner, repo, buggy_sha, fixed_sha, dest).
    jobs: list[tuple] = []
    bug_files: dict[str, list[str]] = {}
    for b in bugs:
        py_files = [f for f in b.files_touched if f.endswith(".py")]
        bug_files[b.key] = py_files
        orep = _owner_repo(b.github_url or "")
        for rp in py_files:
            dest = cache_dir / _flat(b.key) / _flat(rp)
            if orep is None or not b.buggy_commit:
                jobs.append((b.key, rp, None, None, b.buggy_commit, b.fixed_commit, dest))
            else:
                jobs.append((b.key, rp, orep[0], orep[1], b.buggy_commit, b.fixed_commit, dest))

    statuses: dict[tuple[str, str], tuple[str, Path]] = {}

    def work(job):
        key, rp, owner, repo, buggy_sha, fixed_sha, dest = job
        if owner is None or not buggy_sha:
            return (key, rp), ("no_source_url", dest)
        status = _fetch_one(_raw_url(owner, repo, buggy_sha, rp), dest)
        # Recover ambiguous abbreviated SHAs: on 404 with a short SHA, expand to
        # the full 40-char form (verified prefix-match) and retry once.
        if status.startswith("http_4") and len(buggy_sha) < 40:
            full = _resolve_full_sha(owner, repo, buggy_sha, fixed_sha)
            if full:
                status = _fetch_one(_raw_url(owner, repo, full, rp), dest)
        return (key, rp), (status, dest)

    counter: Counter = Counter()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for (key, rp), (status, dest) in ex.map(work, jobs):
            statuses[(key, rp)] = (status, dest)
            counter[status] += 1

    manifest: list[dict] = []
    for b in bugs:
        files = []
        for rp in bug_files[b.key]:
            status, dest = statuses[(b.key, rp)]
            ok = status in ("ok", "cached")
            files.append({
                "repo_path": rp,
                "local_path": str(dest) if ok else None,
                "fetch_status": status,
            })
        manifest.append({"key": b.key, "project": b.project,
                         "buggy_commit": b.buggy_commit, "files": files})
    return manifest, counter


# ----- flag assembly -----

def build_flags(manifest: list[dict], results: dict) -> tuple[dict, dict]:
    """Join manifest + driver results → (flagged, status_report).

    flagged: {bug_key: [{file, lines:[...]}]} — only files the engine ANALYZED
             and where it surfaced >=1 `bottom` row. (Empty list ⇒ no flag.)
    status_report: per-bug per-file analyze status + corpus-wide aggregates,
                   which is the coverage-weakness picture the report leans on.
    """
    from archway_benchmarks.bugsinpy_consumer import consume_bottom_findings

    out = consume_bottom_findings(manifest, results)
    status = dict(out.status_report)
    status["bugs_flagged_any"] = status.pop("bugs_strict_flagged_any", 0)
    return out.flags_strict, status


# ----- CLI -----

def _cmd_fetch(args) -> int:
    bench = BugsInPyBenchmark(corpus_root=Path(args.corpus) if args.corpus else None)
    manifest, counter = build_manifest(
        bench, Path(args.cache), projects=args.projects, limit=args.limit,
        workers=args.workers)
    Path(args.manifest).write_text(json.dumps(manifest, indent=2))
    n_files = sum(len(b["files"]) for b in manifest)
    print(f"manifest: {len(manifest)} bugs, {n_files} touched .py files")
    for status, n in counter.most_common():
        print(f"  fetch {status:18} {n}")
    print(f"  -> wrote {args.manifest} (cache: {args.cache})")
    return 0


def _cmd_build_flags(args) -> int:
    manifest = json.loads(Path(args.manifest).read_text())
    results = json.loads(Path(args.results).read_text())
    flagged, status = build_flags(manifest, results)
    Path(args.out_flags).write_text(json.dumps(flagged, indent=2))
    Path(args.out_status).write_text(json.dumps(status, indent=2))
    print(f"flags: {len(flagged)} bugs with >=1 flag / "
          f"{status['bugs_analyzed_any']} bugs analyzed / {status['total_bugs']} attempted")
    print("  file-status counts:")
    for st, n in sorted(status["file_status_counts"].items(), key=lambda kv: -kv[1]):
        print(f"    {st:18} {n}")
    print(f"  -> wrote {args.out_flags} and {args.out_status}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bugsinpy-flagger",
                                 description="Archway-as-flagger detection pipeline (honest, read-only).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fetch", help="Fetch buggy patch-touched files → manifest.")
    pf.add_argument("--corpus", default=None)
    pf.add_argument("--cache", default="/tmp/bugsinpy_src")
    pf.add_argument("--manifest", default="bugsinpy_manifest_fetch.json")
    pf.add_argument("--projects", nargs="+", default=None)
    pf.add_argument("--limit", type=int, default=None)
    pf.add_argument("--workers", type=int, default=8)

    pb = sub.add_parser("build-flags", help="Join manifest + driver results → flags.json + status.json.")
    pb.add_argument("--manifest", required=True)
    pb.add_argument("--results", required=True, help="Driver output JSON.")
    pb.add_argument("--out-flags", default="bugsinpy_flags.json")
    pb.add_argument("--out-status", default="bugsinpy_flag_status.json")

    pc = sub.add_parser(
        "consume-bottom",
        help="Build strict flags + diagnostic candidates from bottom facts.",
    )
    pc.add_argument("--manifest", required=True)
    pc.add_argument("--results", required=True, help="Driver output JSON.")
    pc.add_argument("--out-flags", default="flags.strict.json")
    pc.add_argument("--out-candidates", default="candidates.diagnostic.json")
    pc.add_argument("--out-status", default="consumer_status.json")

    args = ap.parse_args(argv)
    if args.cmd == "fetch":
        return _cmd_fetch(args)
    if args.cmd == "build-flags":
        return _cmd_build_flags(args)
    if args.cmd == "consume-bottom":
        from archway_benchmarks.bugsinpy_consumer import consume_bottom_findings

        manifest = json.loads(Path(args.manifest).read_text())
        results = json.loads(Path(args.results).read_text())
        out = consume_bottom_findings(manifest, results)
        Path(args.out_flags).write_text(json.dumps(out.flags_strict, indent=2, sort_keys=True))
        Path(args.out_candidates).write_text(
            json.dumps(out.candidates_diagnostic, indent=2, sort_keys=True)
        )
        Path(args.out_status).write_text(json.dumps(out.status_report, indent=2, sort_keys=True))
        summary = out.candidates_diagnostic["summary"]
        print(
            f"candidates: {summary['total_candidates']} total / "
            f"{summary['strict_eligible_candidates']} strict-eligible"
        )
        print(f"  -> wrote {args.out_flags}, {args.out_candidates}, and {args.out_status}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
