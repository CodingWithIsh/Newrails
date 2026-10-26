"""Command line: `python -m plumbing <command>`.

    collect   poll ramp order books and Wise quotes (network; long-running)
    run       rebuild everything; offline from data/cache unless --refresh
"""

from __future__ import annotations

import argparse
import logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="plumbing", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("collect", help="poll ramp order books and Wise quotes")
    p.add_argument("--hours", type=float, default=72.0)
    p.add_argument("--every-min", type=float, default=10.0)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.command == "collect":
        from plumbing.ingest_ramps import collect

        collect(hours=args.hours, every_min=args.every_min)
    return 0
