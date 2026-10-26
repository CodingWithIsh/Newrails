# PLAN: New rails, old margins?

*Numbers Behind the Money, project 2. Plan fixed on 26 October 2026, before any result was computed.*

## 1. The question

Project 1 found that the exchange-rate margin is now **54% of the cost** of sending money from the UK. Upfront fees fell by more than half between 2011 and 2025; the margin hardly moved.

Project 2 asks: **do newer rails (XRP on the XRP Ledger, and the stablecoins USDT and USDC on low-fee networks) remove that margin, or do they move the cost and risk somewhere else?**

We answer it for a £200 transfer from the UK to India, Nigeria, the Philippines, Pakistan and Kenya, with a $200 transfer from the US as a control. The answer has four parts: cost, speed, risk, and the conditions under which each rail breaks even.

This plan is the result of a six-round review of the original brief. [docs/plan_review.md](docs/plan_review.md) records what each round found and what it changed.

## 2. Hypotheses (written before looking at results)

The article will report which of these held, including the ones that failed.

| | Hypothesis | Falsified if |
|---|---|---|
| **H1** Moved, not removed | On the stablecoin rails, conversion costs (on-ramp plus off-ramp spreads, excluding any local premium) are at least as large as the exchange-rate margin of the cheapest digital provider (B1). | That holds in fewer than 3 of the 4 measurable GBP corridors. |
| **H2** Fees move off-chain | Protocol fees are below 0.05% of £200 on XRPL and Solana, but at least 0.5% on Tron when energy is burned. The withdrawal fees exchanges charge are at least 10 times the protocol fee on at least one network. | Any of those three comparisons fails. |
| **H3** Fast ledger, slow last mile | Median on-chain finality is under 10 s on XRPL and Solana and under 2 minutes on Tron. Even so, the end-to-end time for a first-time UK sender is longer than the RPW median delivery time. | The end-to-end time budget is shorter than the RPW median. |
| **H4** Price risk outweighs the saving | For the XRP rail, the 99% 10-minute value-at-risk on £200 is larger than the rail's cost saving over B1 in most corridors. | VaR is smaller than the saving in at least 3 of the 4 corridors. |
| **H5** Pegs mostly hold | Outside stress episodes detected by a rule, USDC and USDT spend more than 99% of minutes within ±0.5% of $1. In the worst episode, USDC moved more than 5% from $1. | Either part fails. |
| **H6** Policy, not technology | Where a local USDT premium exists (India, Kenya), it is larger than the difference in rail costs, and it varies by more than 2 percentage points over the price window. | The premium is smaller than the cost difference, or it is stable. |

## 3. Definitions

**All-in cost.** We use the same definition as RPW, so the rails can be compared directly:

```
cost % = 100 × (1 − R / (A × mid_GBP→local))
```

Here **A** is the amount sent, **R** is the local currency the recipient receives, and **mid** is the mid-market rate at the same moment.

**Crypto rails as a chain of legs.** Each crypto rail is a chain of multiplicative legs. For an asset X (XRP, USDT or USDC):

```
units_X = (A − F_GBP) × (1 − f_on) / ask_X,GBP − W_X          # buy X in the UK, pay the withdrawal fee in X
R       = units_X × [swap legs, if any] × bid_X,local × (1 − f_off) − P_local   # sell locally, pay out
```

**Exchange-rate legs.** The exchange-rate part splits into factors we can measure:

- **on-ramp half-spread**: the order-book ask against the venue mid;
- **off-ramp half-spread**: the bid against the venue mid;
- **basis**: the venue mid against the official cross rate. The destination-side basis is the **local premium**.

**Fee legs.** These are the explicit fees: deposit, trading, withdrawal (the charged fee), and payout.

**Protocol fee.** The network fee, measured on-chain. It is reported beside the charged withdrawal fee, but it is not added to it.

**"Share of cost in exchange rates".** This is exchange-rate legs ÷ total cost, excluding the premium. It is calculated the same way for every rail, so it can be compared with the 54% figure.

**Price drift.** Movement in X between buying and selling is **risk, not expected cost**. We assume its mean is zero and report it as VaR and expected shortfall.

**Benchmarks.** Never just the raw minimum:

- **B1**: the cheapest digital account-to-account service with a margin ≥ 0;
- **B2**: the median digital account-to-account service;
- **B3**: the RPW corridor average.

All three are computed from RPW Q3 2025, interpolated to £200. **W1** and **W2** are the cheapest and median Wise-comparison quotes at £200 in October 2026, used as a contemporaneous cross-check.

## 4. Scope (confirmed by test pulls)

**Corridors.** RPW Q3 2025 figures at £120, transparent services only:

| Corridor | RPW services | RPW avg | Cheapest digital A2A | Off-ramp venues with public order books |
|---|---|---|---|---|
| UK → India | 28 | 1.91% | 0.15% | CoinDCX, WazirX (USDT, USDC, XRP / INR) |
| UK → Nigeria | 31 | 1.96% | −0.12%* | Luno, Quidax (USDT, USDC*, XRP / NGN) |
| UK → Philippines | 38 | 3.33% | 1.11% | Coins.ph (USDT, XRP / PHP) |
| UK → Kenya | 27 | 3.43% | 1.77% | Luno (USDT / KES only) |
| UK → Pakistan | 29 | 2.39% | 0.46% | **none**: P2P only, no public regulated venue |
| US → same five + **Mexico** ($200 control) | 25–58 | 2.7–4.5% | | Bitso (USDT, XRP, RLUSD / MXN) |

\* A negative margin or a very thin market. B1 excludes negative margins.

**Rails:**

| Rail | Network | Why this network |
|---|---|---|
| Bank / money transfer operator | — | RPW plus Wise comparison quotes |
| XRP | XRP Ledger | Specified in the brief. Full-history public servers (s1, s2, xrplcluster) work without a key. |
| USDT | **Tron** | Destination markets trade USDT, and Tron (TRC-20) is the common retail deposit network for it. TronGrid answers without a key, and `getenergyprices` returns the whole history of the fee schedule. |
| USDC | **Solana** | The largest low-fee USDC network. Its public RPC serves historical blocks. **Caveat**: Solana switched consensus (Alpenglow) around 21 October 2026, so its finality is measured only after the switch. |

*Considered and set aside:* **Base**. It has a free RPC, but historical fee data is shallow and few destination exchanges were seen to accept deposits on it.

**Amounts and windows:**

- **Amounts**: £200 headline, plus £120 and £300 (native to RPW), $200 for the control, and a cost curve from £50 to £1,000.
- **Prices**: 1 January 2021 to 30 September 2026.
- **Fees**: 1 October 2024 to 30 September 2026.
- **Ramp snapshots**: at least 72 hours from 26 October 2026.

## 5. Data sources (each verified with a test pull on 26 October 2026)

| Source | Used for | Access | Test result |
|---|---|---|---|
| World Bank RPW Q3 2025 xlsx (datacatalogfiles.worldbank.org) | Traditional benchmark, RPW speed field | Download, CC BY 4.0 | 204,469 rows from Q2 2016. Global average reproduced at **6.363%** (published: 6.36%); UK **4.614%** (article 2: 4.61%). |
| Wise comparison API `api.wise.com/v4/comparisons` | Same-day quotes at any amount, plus the mid-market rate | Public, no key | 17 providers for GBP→INR; 3 to 15 for the other corridors |
| XRPL JSON-RPC (s1/s2.ripple.com, xrplcluster.com) | Ledger close times, fees, sampled transactions | Public | Full history back to ledger 32,570 |
| Solana RPC `api.mainnet-beta.solana.com` | Slot timing, finality lag, block fees | Public, about 100 requests per 10 s | Historical `getBlock` works; finalised lag 0 to 1 slots |
| TronGrid `api.trongrid.io` | Block times, solidification lag, USDT transfer receipts, energy-price history | Public (rate limited without a key) | 29 USDT transfers in a sample block; energy price history from 2018 |
| Binance public data `data.binance.vision` | XRP, TRX, SOL and USDC 1-minute candles | Public monthly zips with checksums | XRPUSDT-1m-2026-09 present |
| Bitstamp API | USDC/USD and USDT/USD (peg), XRP/GBP, GBP/USD | Public | Shows the 11 March 2023 USDC low of about $0.93 |
| Kraken and Coinbase public books | UK on-ramp spreads (XRP, USDC and USDT against GBP) | Public | All books returned (Coinbase XRP-GBP is delisted) |
| CoinDCX, WazirX, Luno, Quidax, Coins.ph, Bitso | Off-ramp books and daily candles | Public | All returned. Luno candles need a key, so Kenya is snapshot only. |
| Frankfurter (ECB), fawazahmed0 currency-api | Daily official FX (ECB lacks NGN, PKR and KES) | Public | Both returned 30 September 2025 |
| FSB G20 KPI report 2025 | Published remittance and Swift speed | PDF | Speed figures sourced from RPW and Swift data |
| Published fee pages (Kraken, Coinbase and Revolut on the UK side; the destination exchanges) | Ramp fees as ranges | Manual, with URL and date | Collected during the build |

## 6. Analysis plan

**RQ1 Cost.** For each corridor, rail and route (on-ramp venue × off-ramp venue), at £200:

- the all-in cost and its legs, with the median and 5 to 95% range across the snapshots;
- comparison with B1, B2, B3, W1 and W2;
- the share of cost in exchange rates;
- results with and without the local premium; for India, the 1% TDS plus 30% tax on gains as a sensitivity;
- a cost-by-amount curve from £50 to £1,000.

**RQ2 Speed.**

- **On-chain, measured**: the distribution of XRPL ledger intervals (from multi-ledger spans), Tron block interval and solidification lag, and Solana slot time and finalised lag after Alpenglow. Each is reported as median, p95, p99 and maximum.
- **Traditional, published**: the RPW `speed actual` distribution per corridor, and the FSB 2025 KPI figures.
- **End to end**: a time budget with every stage labelled *measured* or *published*.

**RQ3 Risk.**

- **(a) XRP price drift.** VaR and expected shortfall at 95% and 99% for horizons of 1, 5, 10 (headline), 30 and 60 minutes, on £200, using historical simulation on 1-minute data. Confidence intervals come from a block bootstrap. Results are split by year and by volatility regime, with a Kupiec backtest. We also report P(drift wipes out the saving over B1).
- **(b) Peg deviation.** For USDC and USDT against USD: the share of minutes beyond ±10, 50 and 100 basis points, the episodes found by the rule, and each episode's depth and recovery time. Includes March 2023 (USDC) and May 2022 (USDT). The main source is fiat-quoted pairs on Bitstamp; Binance USDCUSDT is a cross-check only.
- **(c) Fee spikes.** Distributions of protocol fees from stratified random block samples, tails at p99 and maximum, and the history of Tron's energy price. Results are converted to £ using that day's prices.

**RQ4 Breakeven.**

- a closed-form cost per rail, linear in fixed fees and multiplicative in spreads;
- breakeven surfaces (on-ramp cost × off-ramp cost) with B1 and B2 drawn as contours and the observed routes overlaid;
- Monte Carlo over input ranges, giving P(rail beats B1 or B2) per corridor;
- a tornado chart of one-at-a-time sensitivities.

**Charts (8):**

1. *Hero*: "Where your £200 goes" (stacked legs by rail × corridor).
2. All-in cost against the benchmarks, with ranges.
3. The local USDT premium over time (India, Nigeria, Philippines and Mexico from candles; Kenya from snapshots).
4. Settlement time: on-chain distributions plus the end-to-end time budget.
5. XRP VaR on £200 by horizon (10-minute headline), with bootstrap bands.
6. Stablecoin peg deviation timeline, with the episodes the rule detected.
7. Protocol fee against charged withdrawal fee, by network.
8. Breakeven heatmap (on-ramp × off-ramp) with the observed routes.

**Outputs:**

- `results/summary.csv`: one row per corridor × rail × metric, with point estimate, low, high, method and n.
- `LIMITATIONS.md`, `ASSUMPTIONS.md`, `DATA_SOURCES.md`.
- `writeup/article.md`: 1,200 to 1,500 words in article 2's voice.
- `writeup/cv_summary.md`.

## 7. Engineering design

```
src/plumbing/
  config.py        corridors, windows, constants (seed = 20261026)
  http.py          polite session: retries with backoff, per-host rate limits, timestamped raw cache + SHA-256 manifest
  schemas.py       pydantic models for every ingested record
  ingest_rpw.py    RPW load/clean (adapted from project 1), £200 interpolation, benchmarks
  ingest_prices.py Binance/Bitstamp candles, FX (Frankfurter, fawazahmed0), local-exchange candles
  ingest_ramps.py  order-book snapshots, Wise quotes, fee-schedule loader, snapshot collector
  ingest_xrpl.py   ledger samples, close intervals, transaction fees
  ingest_chain.py  Solana and Tron samples, Tron energy history, live finality samplers
  cost_model.py    leg model, all-in cost, decomposition, breakeven, Monte Carlo
  risk.py          VaR/ES, block bootstrap, Kupiec, peg episodes, fee tails
  plots.py         the 8 charts (one style, colour-blind-safe palette)
  report.py        summary.csv
  cli.py           python -m plumbing {collect, ingest, build, run} [--refresh]
```

**Cache tiers:**

- `data/raw/` is git-ignored. It holds timestamped pulls and its `MANIFEST.csv` (source, URL, pulled_at, sha256, bytes), which *is* committed.
- `data/cache/` is committed. It holds compact Parquet files sufficient to rebuild every number.
- `data/manual/` is committed. It holds fee schedules and the availability matrix as YAML, with URL and access date.

**Commands:**

- `make all` builds from the cache only, offline.
- `make refresh` re-pulls everything.

**Tests** (pytest, offline, fixtures in `tests/fixtures/`):

- unit tests for each cost formula (hand-computed examples, zero fees, missing FX);
- hypothesis property tests (cost ≥ −premium; cost is monotone in every fee);
- schema tests for every ingested dataset;
- RPW regression tests (global 6.36% and UK 4.61% for Q3 2025);
- VaR on synthetic normal data with a known answer, plus a Kupiec sanity check.

**Coverage and CI.** Coverage target ≥ 85% on `src/`. A GitHub Actions workflow runs ruff, mypy (lenient) and pytest with coverage.

## 8. Build order and checkpoints (tests run and committed at each step)

| Step | Work | Done when |
|---|---|---|
| S0 | Scaffold, plan documents | `pytest` runs (empty), plan committed |
| S1 | http/cache layer and snapshot collector; **start the collector in the background (72 h)** | First snapshots land in `data/raw/snapshots/` |
| S2 | RPW ingest, £200 interpolation, benchmarks | Regression tests pass (6.36% and 4.61%) |
| S3 | Prices and FX ingest | Schema tests pass; 69 monthly files verified against their checksums |
| S4 | XRPL ingest | 2,000 sampled ledgers and close-interval spans cached |
| S5 | Solana and Tron ingest | Block samples, energy history and finality samplers cached |
| S6 | Fee schedules and availability matrix (manual YAML) | Every value has a URL, a date and a range |
| S7 | Cost model, breakeven and Monte Carlo | Unit and property tests pass |
| S8 | Risk module | Synthetic VaR test passes; results reproducible with the seed |
| S9 | Plots, notebook, `summary.csv` | `make all` reproduces from the cache |
| S10 | LIMITATIONS, ASSUMPTIONS, DATA_SOURCES, article, CV summary, README | Word count and hypothesis table in the article checked |
| S11 | CI, coverage, fresh-clone test | A clone into a temporary folder runs `make all` with tests green |

**Tiers.**

- **Must** (the article ships on these): RPW, Wise, ramps, protocol fees, XRP VaR, peg, breakeven, hero chart.
- **Should**: premium time series, historical fee samples, time budget, USD control.
- **Could**: regime VaR, RLUSD, Base.

## 9. Risks and fallbacks

| Risk | Fallback (recorded in DATA_SOURCES.md if used) |
|---|---|
| An exchange API goes down mid-collection | The collector records gaps and the analysis uses the remaining snapshots; it never fills gaps by interpolation. |
| Public RPC rate limits | Backoff, smaller samples, alternative public endpoints (xrplcluster ↔ s2; TronGrid ↔ TronScan). |
| Fee pages rendered by JavaScript or region-locked | Use the browser pane to read them; if a fee is still unverifiable, record it as "unverified" with a range from secondary sources. |
| The premium time series confounds official-rate regimes (the naira float in 2023–24) | Mark regime dates on the chart; never average across regimes. |

## 10. Ground rules

- No accounts and no paid keys. Ask before spending money.
- Never fabricate data. Every number traces to a cached pull or a cited page.
- Not investment advice. No token is promoted, and exchanges are named only as data sources.
