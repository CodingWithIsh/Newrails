# Limitations

This file lists what the data cannot show. Read it before quoting any number.

## Who the results describe

- **A sender and a recipient who both already have verified exchange accounts.** The analysis prices the transfer itself, not the cost of getting set up. That cost is real: identity checks on two exchanges (and, in India, a PAN), and minimum withdrawal sizes (Kraken's XRP minimum is 12.05 XRP; its USDT-on-Tron minimum is 6 USDT).
- **Exchange-to-exchange routes only.** Self-custody wallets add their own costs, which are excluded: XRP's 1 XRP account reserve, the rent for a Solana token account, and Tron's higher energy cost when sending to an address that has never held USDT (about 130,000 energy rather than 65,000).
- **No promotions or loyalty tiers.** Fees are the lowest public retail tier. Promotional "first transfer free" rates are excluded from the cheapest-provider benchmark (B1) when they show up as negative margins.

## Availability, regulation and tax

- **Pakistan has no measurable cash-out leg.** No regulated venue publishes a rupee market (PVARA licensing is still in progress), and peer-to-peer markets were not scraped. The result for Pakistan is "not measurable", not "free".
- **The local USDT premium (India about 6%, Kenya about 3.6%) reflects capital controls and tax, not the rail.** Capturing it may be restricted. In India, receiving a remittance as crypto falls outside the regulated FEMA/LRS channels; 1% TDS is withheld at sale (modelled), and gains are taxed at 30% (not modelled, because the gain depends on the recipient's cost basis). Kenya's VASP Act and Nigeria's SEC regime are new; their effect on retail access is not modelled.
- **Route availability is partly unverified.** Some deposit networks (for example CoinDCX accepting USDT on Tron) could not be confirmed from the exchanges' own pages. Every such leg is flagged in `data/manual/availability.yaml`.
- **The UK side has frictions the cost model does not price.** Under FCA rules, a first-time crypto buyer faces a 24-hour cooling-off period and an appropriateness test. The Travel Rule (UK, from September 2023) can delay or block transfers between exchanges.

## Data

- **The bank and MTO benchmark is from August 2025; the crypto prices are from October 2026.** Margins on traditional rails change slowly (article 2: the UK average margin moved from 2.59% to 2.51% in 14 years), but the 14-month gap is real. The Wise comparison quotes (October 2026) are a same-day cross-check. Wise collects those quotes and is itself one of the providers.
- **£200 for traditional providers is interpolated** from each service's own £120 and £300 quotes. It is never extrapolated outside that range.
- **Order books cover days, not seasons.** Spreads and premiums were sampled every 10 minutes for up to 72 hours from 26 October 2026. Weekend, holiday and stress-period liquidity may differ. One CoinDCX outage round is counted, not hidden.
- **Sixteen of the 31 fee entries are unverified.** The provider's page was behind a bot check or a sign-in, so the value came from secondary sources and was entered as a wide range (`verified: false` in `fees.yaml`). The Monte Carlo draws across those ranges.
- **Revolut's own exchange rate is unpublished.** It is modelled as the official rate less a 0–1% margin. Its XRP price is proxied by Kraken's XRP/GBP book.
- **Official exchange rates differ by source.** The ECB rate is used for INR, PHP and MXN. NGN, KES and PKR come from a community-maintained daily feed (from March 2024). Until early 2024, RPW's Nigerian services mostly paid out in US dollars, so no official naira anchor exists for 2022–23.
- **Stablecoin pegs are measured on Bitstamp hourly closes,** with minute data only around stress episodes. Other venues can show deeper or shallower moves.
- **XRP price risk uses Binance XRP/USDT,** converted at a daily GBP/USD rate. Over ten minutes the GBP/USD move is negligible next to XRP's.

## Speed: on-chain is not in the bank

- **Measured:** ledger close and finality times (XRPL about 4 s per ledger, Solana about 0.2 s after Alpenglow, Tron about 57 s to irreversible).
- **Published, not measured:** exchange withdrawal processing, deposit confirmation requirements, and local payout rails (UPI or IMPS, NIP, InstaPay, M-Pesa, SPEI). End-to-end time is dominated by these off-chain steps, plus identity checks and cooling-off periods for new users.
- **Solana's timing describes the five days after its consensus change** (Alpenglow, around 21 October 2026). It should not be compared with figures from before the change.

## Statistics

- **Costs are not volume-weighted.** RPW averages give each service equal weight, as in article 2.
- **Value-at-risk is historical** (2021 to September 2026). It treats the past as a guide. A 30-day rolling version fails a Kupiec backtest (more breaches than promised), so the tails are probably understated.
- **Hypotheses H1–H6 were written before results were computed.** Changes made after the data arrived but before any result was computed are logged in `docs/plan_review.md` (round 7).

This is analysis of public data, not financial advice, and not a recommendation to use or buy any token or exchange.
