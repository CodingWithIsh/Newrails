# Progress (paused 26 Oct 2026, 02:50 UTC, at the usage limit)

## Done
- S0: PLAN.md, docs/plan_review.md, scaffold, ASSUMPTIONS.md, DATA_SOURCES.md (both partial).
- S1: ingest_ramps.py and the collector. **Running in the background until about 29 Oct 02:20 UTC** (pid in `pgrep -fl "plumbing collect"`), writing to data/raw/snapshots/.
- S2: ingest_rpw.py. Reproduces the global average (6.363%) and the UK average (4.614%). Benchmarks at £200: B1 0.01–0.46%, B2 0.6–1.8%.
- S3–S5 code written: ingest_prices.py, ingest_xrpl.py, ingest_chain.py, plus their tests (41 passing at the last run).
- Background pulls started at about 02:47: prices (`logs/prices.log`) and the Solana/Tron fee sample (`logs/chain_build.log`). The XRPL sample is done (cache/xrpl_*). Live samplers: XRPL stream (3 h), Solana and Tron finality (2 h). The Solana sampler was restarted to use batched RPC calls; the first sequential file is kept as `.bak` and must not be used.

## Fee facts collected so far (add to data/manual/fees.yaml)
- **Kraken withdrawals** (support.kraken.com/articles/360000767986, updated 31 Dec 2025, read 26 Oct 2026): XRP 0.05 XRP (minimum 12.05); USDT on Tron 1 USDT (minimum 6); USDC on Solana 1.0323 USDC; USDT on Solana 1.0334; RLUSD 0.5674.
- **Kraken fees** (kraken.com/features/fee-schedule): Pro spot tier 1 is 0.40% maker / 0.80% taker. Stablecoin-base pairs (USDC/GBP, USDT/GBP) are 0.20% / 0.20%. Instant buy is 1% plus an unquantified spread.
- **Coinbase UK** (help.coinbase.com/en-gb/.../pricing-and-fees/fees): simple buy has a spread plus a fee that varies by payment method (1.875% mentioned for limit orders). USDT withdrawals: 0.01% processing fee plus the network fee. Advanced fees are not public without sign-in, so mark them unverified and use a range.

## Next
1. Check that the background jobs finished; fix any failures; commit data/cache/*.parquet.
2. S6: Revolut UK crypto fees (403 to WebFetch, so use the browser pane), Kraken GBP Faster Payments deposit, and the destination exchanges' trading, withdrawal and payout fees (CoinDCX, WazirX, Luno NG/KE, Quidax, Coins.ph, Bitso). Add the network availability matrix and India's 1% TDS plus 30% tax. Write data/manual/fees.yaml and availability.yaml with their schema tests.
3. S7 cost_model.py (book walking, legs, decomposition, breakeven, Monte Carlo) with unit and hypothesis tests.
4. S8 risk.py (VaR/ES, block bootstrap, Kupiec, peg episodes, fee tails) with tests.
5. S9 plots.py, report.py (summary.csv), notebooks/analysis.ipynb, cli `run --all`.
6. S10 LIMITATIONS.md, article (1,200–1,500 words), cv_summary.md, README, DATA_SOURCES.md complete.
7. S11 Makefile, requirements.lock, CI workflow, coverage ≥85%, fresh-clone `make all`.
