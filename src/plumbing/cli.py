"""Command line: `python -m plumbing <command>`.

    collect   poll ramp order books and Wise quotes (network; long-running)
    live      record XRPL, Solana and Tron timing for a while (network)
    run       rebuild results and charts from data/cache (offline); --refresh re-pulls everything first
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

    p = sub.add_parser("live", help="record ledger timing (XRPL stream, Solana and Tron finality)")
    p.add_argument("--minutes", type=float, default=120.0)

    p = sub.add_parser("run", help="rebuild results/ and results/figures/ from data/cache")
    p.add_argument("--all", action="store_true", help="results, figures and the raw-data manifest")
    p.add_argument("--refresh", action="store_true", help="re-pull every source first (network, slow)")
    p.add_argument("--draws", type=int, default=2000, help="Monte Carlo draws per route")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.command == "collect":
        from plumbing.ingest_ramps import collect

        collect(hours=args.hours, every_min=args.every_min)
    elif args.command == "live":
        live(args.minutes)
    elif args.command == "run":
        run(refresh=args.refresh, draws=args.draws, manifest=args.all)
    return 0


def live(minutes: float) -> None:
    import threading

    from plumbing.config import RAW
    from plumbing.ingest_chain import sample_solana_finality, sample_tron_finality
    from plumbing.ingest_xrpl import stream_ledgers
    from plumbing.net import Client, utcnow

    day = f"{utcnow():%Y%m%d}"
    jobs = [
        threading.Thread(target=stream_ledgers, args=(minutes, RAW / "xrpl" / "stream" / f"ledgers_{day}.jsonl")),
        threading.Thread(target=sample_solana_finality, args=(Client(), minutes, 2.0, RAW / "solana" / "live" / f"finality_{day}.jsonl")),
        threading.Thread(target=sample_tron_finality, args=(Client(), minutes, 3.0, RAW / "tron" / "live" / f"finality_{day}.jsonl")),
    ]
    for j in jobs:
        j.start()
    for j in jobs:
        j.join()


def run(refresh: bool = False, draws: int = 2000, manifest: bool = False) -> None:
    import logging

    from plumbing import (
        ingest_chain,
        ingest_prices,
        ingest_ramps,
        ingest_rpw,
        ingest_xrpl,
        plots,
        report,
    )
    from plumbing.config import RAW
    from plumbing.net import write_manifest

    log = logging.getLogger("plumbing")
    if refresh:
        log.info("refreshing every source (network)")
        rpw_raw = ingest_rpw.clean(ingest_rpw.read_xlsx())
        ingest_rpw.build_cache()
        ingest_prices.build_cache(rpw_raw=rpw_raw)
        ingest_xrpl.build_cache()
        ingest_chain.build_cache()
    if (RAW / "snapshots").exists():  # a fresh clone has no raw snapshots: use the committed cache
        ingest_ramps.build_cache()
        ingest_xrpl.build_live()
        ingest_chain.build_live()
        if manifest:
            write_manifest(RAW)
    res = report.build(n_draws=draws)
    for path in plots.make_all(res):
        log.info("wrote %s", path)
    log.info("hypotheses:\n%s", res["hypotheses"][["id", "held", "result"]].to_string(index=False))
