# Assumptions

Every assumption that could change a number is listed here, with its section in the code. Where an assumption is uncertain, the analysis reports the result under alternatives (marked **sensitivity**).

## Transfer

| ID | Assumption | Why | Where |
|---|---|---|---|
| A1 | The headline transfer is **£200** from the UK, with **$200** from the US as a control. | Matches the newsletter's running example. The $200 sender skips the GBP→USD conversion on stablecoin rails. | `config.SEND_GBP`, `config.SEND_USD` |
| A2 | RPW prices UK services at £120 and £300, so £200 is a **linear interpolation of each service's own quotes**, fee and margin separately: `x(200) = x(120) + (x(300) − x(120)) × 80/180`. | Most fees are flat or stepwise in amount. Linear interpolation between two observed points needs no extrapolation. **Check**: live Wise-comparison quotes at exactly £200. | `ingest_rpw.interpolate` |
| A3 | Costs are measured against the **mid-market rate at the same moment**: Wise's mid-market quote for live snapshots, and RPW's own interbank rate for RPW. | This is RPW's definition of total cost, so the rails compare like for like. | `cost_model` |

## Benchmarks

| ID | Assumption | Why |
|---|---|---|
| A4 | **B1** is the cheapest *digital, account-to-account* RPW service (access point Internet, delivery to a bank account) with an exchange-rate margin of at least 0. **B2** is the median of that group. **B3** is the corridor average. | Crypto rails are digital and end in an account. Negative margins are promotions or reference-rate artefacts (article 2), not prices a sender can rely on. |

## Rails

| ID | Assumption | Why |
|---|---|---|
| A5 | Rails are XRP on the XRP Ledger, USDT on Tron and USDC on Solana. | See PLAN.md §4. Destination markets trade USDT, Tron is the common retail network for it, and Solana is the largest low-fee USDC network. All have free public data. |
| A6 | Routes go **exchange to exchange**: buy on a UK venue, withdraw on-chain to a destination venue, sell there, and withdraw to a local bank. Self-custody wallets are out of scope. | This is the simplest path a retail sender could follow. It avoids wallet set-up costs (XRP reserve, Solana token-account rent), which are listed in LIMITATIONS. |
| A7 | Price drift between buying and selling has a mean of zero. It is treated as risk (VaR and expected shortfall), not as an expected cost. | Assuming a positive or negative drift would be a market view. |
| A8 | Pakistan has no regulated venue with public market data, so crypto rails there are recorded as **not measurable**, not as zero cost. | No unofficial P2P endpoint is scraped. |

## Windows (fixed before results)

| ID | Window | Use |
|---|---|---|
| A9 | 1 Jan 2021 to 30 Sep 2026 | XRP price risk, stablecoin peg, local-premium history |
| A10 | 1 Oct 2024 to 30 Sep 2026 | Network fee distributions |
| A11 | At least 72 h from 26 Oct 2026, every 10 min | Ramp order books and Wise quotes |
| A12 | 10-minute headline horizon for XRP VaR (also 1, 5, 30 and 60 min) | The time between buying in the UK and selling at the destination: withdrawal processing plus network plus deposit crediting |

## Fees, ramps and routes

| ID | Assumption | Why | Where |
|---|---|---|---|
| A13 | Every fee is drawn **uniformly within its published range**. Unverified fees use deliberately wide ranges. | We have no information on where within a range a sender lands. Uniform draws keep that ignorance visible in the 5–95% ranges. | `cost_model.draw_fees`, `data/manual/fees.yaml` |
| A14 | **Spreads come from walking the real order book** for the transfer size, never from a quoted spread. | £200 is small next to the books measured, so slippage is negligible, except on thin books (Luno USDT/KES, USDC/NGN), where it is real and shown. | `cost_model.walk_asks/walk_bids` |
| A15 | A draw the book is too thin to fill is **counted as unfilled**, not dropped silently. | Thin books are a finding about liquidity. | `monte_carlo` (`unfilled_share`) |
| A16 | **Revolut converts GBP to stablecoins at the official rate less a 0–1% margin.** Revolut's XRP price is proxied by Kraken's XRP/GBP book plus the same margin. | Revolut publishes no order book or margin. Its fee document charges no percentage fee on fiat↔stablecoin exchanges. | `cost_model.evaluate`, `fees.yaml` |
| A17 | **USD senders' deposit fees are zero.** | No published fee for ACH or wire deposits to Kraken was readable. Applies to the US control corridors only. | `fee_ranges` |
| A18 | **Where a coin has no local market, it is swapped into USDT on the same exchange first** (USDC→USDT on Luno for Nigeria and Kenya; XRP→USDT on Luno for Kenya), using the local trading fee. | That is the route a sender would actually take. Each swap is a separate leg with its own spread and fee. | `cost_model.OFFRAMPS` |
| A19 | **India's 1% TDS is a cost leg**, reported separately. The 30% tax on gains is **not** modelled. | TDS is withheld at sale and can be credited later, so it is a cash-flow cost. The tax on gains depends on the recipient's cost basis. | `fees.yaml: india_tax` |
| A20 | **The "local premium" is the destination exchange's mid price against the official USD rate at the same moment** (Wise's mid-market quote in the same 10-minute round). For XRP sold directly into local currency, it is XRP's local price against its UK price times the official GBP rate. | This keeps policy-driven premiums apart from the rail's own costs. | `cost_model.simulate` |
| A21 | **"Exchange-rate share" = (spread + fx) / (fee + spread + fx)**, excluding premium and tax. For RPW it is margin / total cost. | This mirrors project 1's 54% statistic. | `summarise`, `ingest_rpw.benchmarks` |

## Risk

| ID | Assumption | Why |
|---|---|---|
| A22 | XRP returns use Binance XRP/USDT at 1 USDT = $1, converted to pounds at a daily GBP/USD rate. | Over 10 minutes, GBP/USD and USDT/USD moves are negligible next to XRP's. Binance is the deepest XRP market, and Bitstamp XRP/GBP minute bars are often stale. |
| A23 | Overlapping 10-minute windows; a moving-block bootstrap with 1-day blocks and 200 replicates for the CIs; the Kupiec test on non-overlapping hourly tests against a 30-day rolling historical VaR. | Overlap maximises data use; block bootstrap and non-overlapping tests deal with the dependence. |
| A24 | A volatility regime is the quintile of the **trailing** 24-hour realised volatility, known before a transfer starts. | A sender can see it beforehand, so it is usable advice, not hindsight. |
| A25 | Stablecoin stress episodes are hours whose **close** is more than 0.5% from $1, merged when less than 24 h apart. Prices outside $0.50–$1.50 are data errors, dropped and counted. | Bitstamp's hourly highs and lows include stray trades (see plan review round 7). |

## Speed

| ID | Assumption | Why |
|---|---|---|
| A26 | XRPL finality is about two ledger intervals (submit in one, validated by the next). Solana finality is the processed→finalised slot lag times the slot time. Tron finality is the head→solidified lag. | These are how each protocol defines finality. All are measured live, not taken from documentation. |
| A27 | Bank/MTO speed is RPW's own `speed actual` field. It is not converted to hours except at band edges. | RPW records bands, not times. |
