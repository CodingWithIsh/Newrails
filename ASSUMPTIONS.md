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

*More assumptions are added as each module is built (fee schedules, tax, swap legs).*
