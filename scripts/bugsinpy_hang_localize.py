"""Read-only hang localizer for translate non-termination (BugsInPy workstream).

For a file whose `translate_module` does not terminate, a watcher thread dumps the live
Python stack of all threads at several wall-clock checkpoints (faulthandler). If the same
translate frames recur across checkpoints, the hang is a loop/recursion there — a concrete
locus for WS-1. Read-only: runs the pinned engine's translate, edits nothing.

Usage (pinned worktree hatch env):
    hatch run python <repo>/scripts/bugsinpy_hang_localize.py <key> <src_path> <hard_cap_s> <out_txt>
"""
import faulthandler
import signal
import sys
import threading
import time


class TO(Exception):
    pass


def _onalarm(signum, frame):
    raise TO()


def main():
    key, path, cap, out_txt = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    out = open(out_txt, "w")
    out.write(f"# hang-localize {key}  src={path}  cap={cap}s\n")
    out.flush()

    checkpoints = [c for c in (12, 30, 55, 80) if c < cap]
    stop = threading.Event()

    def watcher():
        start = time.perf_counter()
        for c in checkpoints:
            if stop.wait(c - (time.perf_counter() - start)):
                return
            out.write(f"\n===== STACK @ ~{c}s =====\n")
            out.flush()
            faulthandler.dump_traceback(file=out, all_threads=True)
            out.flush()

    from sd_core.translate.modules import translate_module

    src = open(path, encoding="utf-8", errors="replace").read()
    signal.signal(signal.SIGALRM, _onalarm)

    w = threading.Thread(target=watcher, daemon=True)
    w.start()
    t0 = time.perf_counter()
    signal.alarm(cap)
    try:
        translate_module(src)
        signal.alarm(0)
        out.write(f"\n{key}: translate FINISHED in {time.perf_counter()-t0:.1f}s (no hang)\n")
    except TO:
        out.write(f"\n{key}: hard cap {cap}s reached — translate did NOT terminate\n")
    except BaseException as e:
        out.write(f"\n{key}: translate raised {type(e).__name__}: {str(e)[:120]} "
                  f"after {time.perf_counter()-t0:.1f}s\n")
    finally:
        stop.set()
        out.flush()
        out.close()
    print(f"{key}: wrote {out_txt}")


if __name__ == "__main__":
    main()
