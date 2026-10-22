"""Run the evals from the repository root: `uv run python -m evals <demo|banking77>`."""

import argparse
import asyncio

from evals.routing import run_banking77, run_demo
from request_routing.config import TRACES_DIR
from request_routing.tracing import configure_tracing


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="The five Banking77 demo messages: intent and handling.")
    demo.add_argument("--concurrency", type=int, default=5, help="Use 1 to follow the messages one by one.")
    demo.add_argument("--rows", type=int, nargs="+", help="Only these demo rows, in this order.")
    banking77 = commands.add_parser("banking77", help="Intent accuracy on a seeded Banking77 test sample.")
    banking77.add_argument("--n", type=int, default=30)
    banking77.add_argument("--seed", type=int, default=7)
    banking77.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()

    configure_tracing(TRACES_DIR)
    if args.command == "demo":
        asyncio.run(run_demo(args.concurrency, args.rows))
    else:
        asyncio.run(run_banking77(args.n, args.seed, args.concurrency))


if __name__ == "__main__":
    main()
