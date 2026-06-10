"""Read-only cProfile root-cause probe for the P0 translate-perf wall (BugsInPy WS).

Run #6 localized the P0 hot path (faulthandler) to
`translate_stmt.py:657 translate_functiondef` -> `sequence.py:27` and offered an
OUTSIDE-READ hypothesis: the super-linear cost is branch/scenario STATE FAN-OUT
(`declare()` over a coproduct state set; `assemble_propagating`). That was a hypothesis,
NOT a verified root cause. This probe CONFIRMS or REFUTES it deterministically by
cProfiling a single `translate_module` run and reporting WHICH functions actually
consume the time and HOW MANY TIMES they are called.

Read-only against the pinned engine: it imports and RUNS the engine's translate but
edits nothing, changes no pin. It is a measurement.

Per file it:
  * cProfiles `translate_module(src)` under a hard SIGALRM cap (so a non-terminating
    file still yields a partial profile — the profiler is disabled in `finally`),
  * writes the raw pstats `.prof` (re-analyzable later),
  * writes a text summary: top-N by tottime and by cumtime, plus a TARGETED call-count
    table for the functions the fan-out hypothesis implicates (declare / propagate /
    compose / coproduct-state ops / the localized translate frames). The call COUNTS
    are the test: if `declare`/state-fan-out calls dwarf the statement count
    super-linearly, the hypothesis holds; if the time is in one tight non-fan-out loop,
    it is refuted.

Usage (pinned read-only worktree hatch env):
    hatch run python <repo>/scripts/bugsinpy_cprofile_probe.py <key> <src_path> <cap_s> <out_prefix>

Writes <out_prefix>.prof (binary pstats) and <out_prefix>.txt (human summary).
"""
import cProfile
import io
import pstats
import signal
import sys
import time


class TO(Exception):
    pass


def _onalarm(signum, frame):
    raise TO()


# Function-name substrings the fan-out hypothesis implicates, plus the localized P0
# frames and the top translate-error loci, so the targeted table is self-contained.
TARGETS = [
    "declare", "propagat", "assemble", "compose", "coproduct", "summand",
    "scenario", "branch", "get_states", "is_frozen", "permutation", "gather_inputs",
    "translate_functiondef", "translate_classdef", "translate_stmt_sequence",
    "translate_stmt", "translate_module", "pop_expr", "next_branch", "close_expr",
    "make_permutation", "freeze", "merge", "join", "collapse_scope",
]


def _func_label(func):
    # func is (filename, lineno, funcname)
    fn = func[0] or ""
    if "sd_core/" in fn:
        fn = "sd_core/" + fn.split("sd_core/", 1)[-1]
    return f"{fn}:{func[1]} {func[2]}"


def _targeted_table(stats):
    """Rows for any profiled function whose name matches a TARGET substring,
    sorted by primitive call count (the fan-out signal)."""
    rows = []
    for func, (cc, nc, tt, ct, callers) in stats.stats.items():
        name = func[2] or ""
        if any(t in name for t in TARGETS):
            rows.append((nc, cc, tt, ct, _func_label(func)))
    rows.sort(reverse=True)  # by primitive ncalls desc
    return rows


def main():
    key, path, cap, out_prefix = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    from sd_core.translate.modules import translate_module

    src = open(path, encoding="utf-8", errors="replace").read()
    n_lines = src.count("\n") + 1
    n_def = sum(1 for ln in src.splitlines() if ln.lstrip().startswith("def "))
    n_if = sum(1 for ln in src.splitlines()
               if ln.lstrip().startswith(("if ", "elif ", "for ", "while ", "try", "with ")))

    signal.signal(signal.SIGALRM, _onalarm)
    prof = cProfile.Profile()
    t0 = time.perf_counter()
    outcome = "?"
    detail = ""
    prof.enable()
    try:
        signal.alarm(cap)
        translate_module(src)
        signal.alarm(0)
        outcome = "FINISHED"
    except TO:
        signal.alarm(0)
        outcome = "HARD_CAP"
        detail = f"translate did not finish in {cap}s (partial profile)"
    except BaseException as e:
        signal.alarm(0)
        outcome = "ERROR"
        detail = f"{type(e).__name__}: {str(e)[:160]}"
    finally:
        prof.disable()
    elapsed = time.perf_counter() - t0

    prof.dump_stats(out_prefix + ".prof")

    sio = io.StringIO()
    st = pstats.Stats(prof, stream=sio)  # full paths kept so sd_core frames are identifiable
    hdr = (f"# cProfile P0 root-cause probe  key={key}\n"
           f"# src={path}\n"
           f"# source: {n_lines} lines, ~{n_def} def, ~{n_if} compound-stmt headers\n"
           f"# translate outcome={outcome} elapsed={elapsed:.1f}s (PROFILED — wall is "
           f"inflated vs unprofiled){(' | ' + detail) if detail else ''}\n"
           f"# total primitive calls profiled={st.total_calls}\n")
    sio.write(hdr)

    sio.write("\n===== TOP 35 BY tottime (self time — where cycles burn) =====\n")
    st.sort_stats("tottime").print_stats(35)

    sio.write("\n===== TOP 35 BY cumtime (inclusive — call-tree cost) =====\n")
    st.sort_stats("cumulative").print_stats(35)

    sio.write("\n===== TARGETED: fan-out-hypothesis functions, by primitive ncalls =====\n")
    sio.write("# ncalls(primitive)  ncalls(total)  tottime  cumtime  function\n")
    for nc, cc, tt, ct, label in _targeted_table(st)[:50]:
        sio.write(f"{nc:>12} {cc:>14} {tt:>10.3f} {ct:>10.3f}  {label}\n")

    sio.write(f"\n# RATIO CHECK (fan-out test): source has ~{n_def} defs / ~{n_if} "
              f"compound headers. If declare/propagate/compose primitive ncalls are "
              f"super-linear in these counts, the state-fan-out hypothesis holds.\n")

    open(out_prefix + ".txt", "w").write(sio.getvalue())
    print(f"{key}: outcome={outcome} elapsed={elapsed:.1f}s calls={st.total_calls} "
          f"-> {out_prefix}.txt / .prof")


if __name__ == "__main__":
    main()
