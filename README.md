# New rails, old margins?

**Does crypto remove the hidden cost of sending money home, or just move it?** Project 2 of *Numbers Behind the Money*.

Project 1 ([numbers-behind-the-money](https://github.com/CodingWithIsh/numbers-behind-the-money)) found that the exchange-rate margin is now **54%** of the cost of sending money from the UK. This project compares a £200 transfer through banks and money transfer operators (MTOs) with three newer rails: **XRP on the XRP Ledger, USDT on Tron and USDC on Solana**. The comparison covers the UK to India, Nigeria, the Philippines, Kenya and Pakistan, with $200 from the US (to the same countries plus Mexico) as a control.

![Where your £200 goes](results/figures/fig1_where_200_goes.png)

## Findings (provisional: first four hours of a 72-hour order-book collection)

| | |
|---|---|
| Share of cost in exchange rates | **17%** on crypto routes (median) vs **54%** for the average UK transfer. Spreads are basis points on liquid books. |
| Where the cost went | Flat withdrawal fees. Kraken's USDC-on-Solana fee is **~760×** the network fee; Revolut charges £3 (1.5% of £200). |
| vs the cheapest digital bank/MTO | Excluding local premiums, the best crypto route won in **≤ 4%** of simulations in every corridor. |
| The exception | USDT sells **6.3%** above the official rate in India and **3.6%** in Kenya. These premiums come from capital controls and tax, not technology. |
| XRP price risk | 10-minute 99% VaR **£2.40** on £200 (90% CI £2.31–£2.49). A 30-day rolling VaR fails the Kupiec test. |
| Stablecoin pegs | Within ±0.5% in **99.8%** of hours. USDC touched **$0.81** in March 2023. |
| Speed | XRPL ~4 s per ledger, Solana ~0.2 s to finality (after Alpenglow), Tron ~57 s to irreversible. 57–85% of bank/MTO services already deliver within an hour. |
| Pakistan | No regulated exchange publishes a rupee market, so the cash-out leg can't be measured. |

The six hypotheses were fixed before any result was computed ([PLAN.md](PLAN.md)). Five held; H4 did not ([results/hypotheses.csv](results/hypotheses.csv)).

## Quick start (fresh clone, offline, ~2 minutes)

```bash
make setup     # .venv + pinned requirements (Python 3.12+; developed on 3.14)
make all       # lint, 105 tests (96% coverage), results/*.csv, 8 charts, executed notebook
```

`make all` reads only the committed `data/cache/`. To re-pull everything from the original sources (network, about 20 minutes, no keys or accounts needed):

```bash
make refresh   # RPW, prices, FX, XRPL/Solana/Tron samples
make collect   # 72 h of order-book and Wise snapshots
make live      # 2 h of live ledger timing
```

## How it works

| Module | Job |
|---|---|
| `ingest_rpw.py` | World Bank RPW Q3 2025. Reproduces the published 6.36% global and 4.61% UK averages, interpolates each service to £200, and builds benchmarks B1/B2/B3. |
| `ingest_ramps.py` | Order books from 9 exchanges, Wise comparison quotes, and the snapshot collector. Also loads the hand-collected fee and availability files. |
| `ingest_prices.py` | Binance XRP 1-minute candles (checksummed), Bitstamp USDC/USDT pegs, ECB and other official FX rates, and local USDT markets. |
| `ingest_xrpl.py`, `ingest_chain.py` | Stratified samples of historical blocks for fees, plus live sampling of ledger and finality timing. |
| `cost_model.py` | Each route is a chain of legs (fee, spread, fx, premium, tax) that must reconcile exactly with the amount received. Also Monte Carlo and closed-form breakeven. |
| `risk.py` | VaR/ES with block-bootstrap CIs, the Kupiec backtest, peg bands and episodes, and fee tails. |
| `report.py`, `plots.py` | Every table in `results/` and every chart in `results/figures/`, drawn from the same numbers. |

Read next: [PLAN.md](PLAN.md) and the [six-round plan review](docs/plan_review.md), [ASSUMPTIONS.md](ASSUMPTIONS.md), [LIMITATIONS.md](LIMITATIONS.md), [DATA_SOURCES.md](DATA_SOURCES.md), the [article draft](writeup/article.md), and [results/summary.csv](results/summary.csv) (estimate, low, high, method, n for every number).

## Data and licence

Sources are listed in [DATA_SOURCES.md](DATA_SOURCES.md). World Bank RPW is CC BY 4.0 ("The World Bank, Remittance Prices Worldwide, remittanceprices.worldbank.org"). Exchange market data is used for research under each venue's public API terms. Check those terms before redistributing `data/cache/`. Code: MIT.

This is analysis of public data, not financial advice, and not a recommendation to use or buy any token or exchange.
