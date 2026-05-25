import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="archway-bench")
    sub = parser.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="Run a benchmark suite")
    run.add_argument("suite", help="Suite name under suites/")

    sub.add_parser("list", help="List available suites")

    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return 0

    if args.cmd == "list":
        print("(no suites yet)")
        return 0

    if args.cmd == "run":
        print(f"Running suite: {args.suite}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
