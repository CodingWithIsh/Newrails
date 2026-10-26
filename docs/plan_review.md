# How the plan was refined

The plan in [PLAN.md](../PLAN.md) is the output of a short recursive review. **v0** was the original brief. Each round read the current plan through one lens, listed what would go wrong, and changed the plan. The rule for stopping: end when a round produces no change that would alter how a headline number is defined or what a chart shows.

Round 1 was driven by evidence (test pulls on 26 October 2026). Later rounds were critique.

---

## Round 1: does the data say what the brief assumes? (test pulls)

| # | What the test pull showed | Change to the plan |
|---|---|---|
| 1.1 | RPW does not price £200 for UK senders. It prices **£120 and £300** (`cc1`, `cc2`; the World Bank's equivalents of $200 and $500). | Interpolate each service linearly between its own £120 and £300 quotes to get £200 (fee and margin separately). Report £120 and £300 natively as well. Check the £200 estimate against live quotes at exactly £200 (1.2). |
| 1.2 | The latest RPW release is still **Q3 2025** (collected 8 to 26 August 2025). The crypto data is from October 2026, a 14-month gap. | Add a same-day benchmark: Wise's public comparison API returns quotes at exactly £200 from 17 providers for GBP→INR, banks included, with collection timestamps. Caveat: Wise collects these quotes and is itself one of the providers, so this is a cross-check, not the primary benchmark. |
| 1.3 | "The cheapest traditional option" is fragile. The UK→India minimum is 0.15% (State Bank of India, to an SBI account). Some totals are negative: Pakistan −1.43%, Nigeria −0.12% (promotions or reference-rate artefacts, as article 2 warned). | Use three benchmarks, never the raw minimum alone. **B1**: the cheapest digital, account-to-account service with a non-negative margin. **B2**: the median digital account-to-account service. **B3**: the RPW corridor average. |
| 1.4 | Retail users never pay the network fee directly. They pay the exchange's flat withdrawal fee. | Show two lines: the **protocol fee** (measured on-chain) and the **charged fee** (published exchange schedule). The gap between them is a finding. |
| 1.5 | Cashing out is not a fee schedule; it is a **local market price**. USDT best bid against the mid-market rate on 26 October 2026: India **+6.0%** (CoinDCX), Kenya **+3.1%** (Luno), Nigeria **+0.5%** (Luno, Quidax), Philippines **−0.2%** (Coins.ph), Mexico **−0.2%** (Bitso). | Measure the off-ramp by walking public order books for the actual transfer size. Keep the **local premium** as a separate line and never net it silently into "cost". Model India's 1% TDS and 30% tax on gains as a sensitivity. The premium reflects capital controls and tax, not technology. |
| 1.6 | Pakistan has no regulated venue that publishes market data. PVARA licensing is still in progress, and only P2P markets exist. | Keep Pakistan in scope. The finding is "no measurable last mile", not a blank row. Do not scrape unofficial P2P endpoints. |
| 1.7 | **Solana changed consensus five days ago** (Alpenglow, around 21 October 2026). Live sampling shows a finalised lag of 0 to 1 slots, against about 32 slots under TowerBFT. | Treat it as a regime change. Measure after the switch, cite the figure from before it, and never pool the two. |
| 1.8 | XRPL `close_time` is rounded to `close_time_resolution` (10 s), so per-ledger intervals come out in steps. | Estimate the ledger interval from spans of many ledgers, and report the rounding. |
| 1.9 | Coinbase's XRP-GBP market is delisted. Bitstamp's XRP/GBP minute bars are often stale (zero volume). | Compute VaR from Binance XRPUSDT 1-minute data (monthly files with published checksums), converted with GBP/USD. Use Bitstamp and Kraken XRP/GBP as a cross-check, and show the bias stale bars cause. |
| 1.10 | USDC is thin at the destination: Luno USDC/NGN bid 1,320 against ask 1,569, and no USDC/KES market at all. Destination markets trade **USDT**. | Model the USDC route with an explicit USDC→USDT swap where needed. "USDC is what UK platforms favour; USDT is what local markets trade" becomes a finding. |
| 1.11 | Tron's USDT fee is not tiny. It is about 64k to 130k energy at a governance-set price (100 sun since 29 August 2025), roughly 6.5 to 13 TRX when burned. Many senders rent or stake energy instead. | Fee model per mechanism. XRPL: load-based escalation. Solana: base fee plus a priority market. Tron: a resource model whose price is set by governance (history from `getenergyprices`). |

## Round 2: would a statistician sign off?

| # | Problem | Change |
|---|---|---|
| 2.1 | Single order-book snapshots carry no sampling uncertainty. | Run a snapshot collector: order books every 10 minutes and Wise quotes hourly, for at least 72 hours. Add daily candle histories (WazirX, CoinDCX, Quidax, Coins.ph, Bitso) to track the premium over years. Report the median and the 5 to 95% range. |
| 2.2 | Overlapping 10-minute windows are autocorrelated, so naive confidence intervals are too narrow. | Use block-bootstrap confidence intervals, a Kupiec backtest on non-overlapping windows, and VaR split by calendar year and by volatility regime. |
| 2.3 | Results could depend on the time window chosen. | **Fix the windows before looking.** Prices: 1 January 2021 to 30 September 2026. Fees: 1 October 2024 to 30 September 2026. On-chain samples: stratified random. Stress episodes: found by a rule (hourly \|deviation\| > 0.5%), not picked by hand. |
| 2.4 | A single breakeven point is brittle. | Monte Carlo over the input ranges gives P(rail beats B1) and P(rail beats B2) per corridor. Add a one-at-a-time tornado chart. |
| 2.5 | Hypotheses written after the results invite storytelling. | Write H1 to H6 into PLAN.md **before** computing results. The article reports which held and which didn't. |

## Round 3: would a payments practitioner find it credible?

| # | Problem | Change |
|---|---|---|
| 3.1 | "Remove or move?" needs a like-for-like split. | Classify every leg as a **fee** or an **exchange-rate cost**, then compute each rail's "share of cost in exchange rates", directly comparable with the 54% figure. |
| 3.2 | A GBP sender converts currency twice on a stablecoin rail (GBP→USD on-ramp, USD→local off-ramp). | Add a **USD-sender control** ($200, from the US to the same corridors plus Mexico), where one conversion disappears. Mexico is the world's largest corridor and Bitso publishes XRP, USDT and RLUSD books. |
| 3.3 | On-chain finality is not money in the recipient's account. | Add a time budget for each stage: bank→exchange, KYC and the FCA's 24-hour cooling-off for first-time buyers, withdrawal processing, deposit confirmations, and the local payout rail. Mark which numbers are **measured** and which are **published**. |
| 3.4 | Bank-rail speed must not be invented. | Use RPW's own `speed actual` field (69% of UK services in these corridors deliver in under an hour) and the FSB's 2025 KPI report (remittances and Swift). Cite both. |
| 3.5 | Ripple's ODL is a B2B product; the retail XRP route is do-it-yourself. | State this in LIMITATIONS. RLUSD on XRPL is noted as out of scope. |
| 3.6 | A rail only counts if the network path exists end to end. | Build a **rail availability matrix** (on-ramp × network × off-ramp) from published deposit and withdrawal pages, marking each Yes, No or Unverified with URL and date. |

## Round 4: would a Substack reader get it in one read?

| # | Problem | Change |
|---|---|---|
| 4.1 | Eight charts but no single picture that answers the question. | Hero chart: **"Where your £200 goes"**, one stacked bar per rail, coloured fee vs exchange rate vs local premium. |
| 4.2 | Voice drift. | Match article 2: first person, British spelling, question headings, "How I did this, and what the data can't tell us", and a closing "What's next". 1,200 to 1,500 words, 5 to 6 charts. |
| 4.3 | Article 2 promised a look at "which providers are consistently the cheapest". | Say so in the piece. Crypto has to beat the cheapest provider, so the benchmark section partly delivers on that promise. |
| 4.4 | The piece could read as crypto promotion. | No "best exchange" claims and no affiliate links. Exchanges appear only as data sources. Every saving is shown next to its risk, and a not-advice line is included. |

## Round 5: would a hiring manager clone it?

| # | Problem | Change |
|---|---|---|
| 5.1 | A fresh clone must reproduce everything, but the raw pulls are large (RPW 50 MB; Binance minute data about 110 MB). | Two-tier cache. `data/raw/` is git-ignored and timestamped, with a SHA-256 manifest that *is* committed. `data/cache/` is committed compact Parquet that is enough to rebuild every number. `make all` reads only the cache; `make refresh` rebuilds it from the network. |
| 5.2 | Network code is hard to test offline. | Split each ingest into `fetch_*` (thin) and `parse_*` (pure, tested against fixtures), with a fake HTTP session in tests. |
| 5.3 | The local interpreter is Python 3.14 with pandas 3.1. | Pin versions in `requirements.lock`, run CI on the versions that pin installs on, and state them in the README. |
| 5.4 | Reviewers skim. | Put the hero chart, three numbers and the `make all` command at the top of the README. |

## Round 6: can it be finished?

| # | Problem | Change |
|---|---|---|
| 6.1 | Scope creep. | Tier the work Must / Should / Could; the article ships on Must. |
| 6.2 | Public RPC limits, especially Solana `getBlock` at about 1 to 3 MB per block. | Cap samples: 240 Solana blocks, 2,000 XRPL ledgers, 1,000 Tron blocks. Polite backoff, everything cached. |
| 6.3 | The snapshot collector needs wall-clock time. | Start it first, before the other ingest work. |

**Convergence.** Round 6 changed only the build order and the sample caps, with no change to any headline definition, so the review stopped there.

---

## Round 7: corrections forced by the data (after collection, before any result)

These changes were made after the data arrived but before any cost or risk result was computed. They are recorded here so nothing is changed silently.

| # | What the data showed | Change |
|---|---|---|
| 7.1 | The stress-episode rule used each hour's **high and low**. Bitstamp's highs and lows include stray trades (one USDT print at $2,959 in November 2022), and the rule found 329 "episodes". | The rule now uses the **hourly close**, and prices outside $0.50–$1.50 are dropped as data errors and counted (`peg_bad_prints.parquet`: 3 hourly and 8 minute candles, all USDT). This leaves 32 episodes. The worst is USDC at $0.863 (11–13 March 2023, SVB); USDT's lowest was $0.97 (May 2022, Terra). |
| 7.2 | The first two minutes of the Solana finality sampler queried the three commitment levels one after another, so the finalised slot could come out *newer* than the processed one. | That file is set aside (`*_DISCARDED.jsonl.bak`) and never read. Sampling restarted with all three levels in one JSON-RPC batch. |
| 7.3 | Bitstamp USDT/USD starts on 10 June 2021, not 1 January. CoinDCX and Coins.ph serve only their last 1,000 days (from February 2024). Official NGN, KES and PKR rates are daily only from March 2024; before that, five quarterly RPW interbank points are available. | Each series is reported over the dates it actually covers. India's premium history before 2024 uses WazirX. |
| 7.4 | The peg is measured on **hourly closes** for the full window (minute data is held only around episodes). | H5 is tested as a "share of hours", and the article says so. |
