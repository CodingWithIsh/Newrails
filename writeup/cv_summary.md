# CV summary: New rails, old margins? (provisional numbers; refresh after the 72-hour collection)

## Three bullets

- Built a reproducible Python pipeline (pandas, SciPy, pydantic, pytest/Hypothesis, CI) comparing the all-in cost of £200 remittances on bank/MTO rails with XRP, USDT on Tron and USDC on Solana across 5 UK corridors. It walks live order books from 9 exchanges, uses ~390k sampled on-chain transactions and 3M one-minute prices, has 131 tests (96% coverage), and reproduces the World Bank's 6.36% global average.
- Showed that the newer rails shrink the exchange-rate share of cost from 54% (UK average) to a median of 17%. The cost moves into flat fees (Kraken's USDC withdrawal fee is ~760× the network fee), and once local premiums were excluded, the best crypto route beat the cheapest digital provider in at most 4% of simulations in each of 4 corridors.
- Quantified risk and speed with pre-registered hypotheses. XRP's 10-minute 99% VaR is £2.40 on £200 (block-bootstrap CI; a 30-day rolling VaR fails the Kupiec test). USDC fell to $0.81 in March 2023. Solana finalises in about 0.2 s after Alpenglow, yet 57–85% of bank/MTO services already deliver within an hour.

## One-paragraph description

*New rails, old margins?* tests whether crypto rails remove the hidden exchange-rate cost of sending money home or just move it. I built a Python package that ingests the World Bank's Remittance Prices Worldwide, live order books from UK and destination-country exchanges, published fee schedules, and on-chain data from public XRP Ledger, Solana and Tron nodes. It models each transfer as a chain of fees, spreads and premiums that reconciles exactly with the amount received, and it reports uncertainty through Monte Carlo and block-bootstrap intervals rather than point estimates. Six hypotheses were fixed before the analysis. The finding: the exchange-rate margin largely disappears on liquid markets, but flat withdrawal fees, price risk and capital-control premiums take its place. The cheapest traditional providers still win. Everything rebuilds from cached data with `make all`, and the results are written up for my Substack, *Numbers Behind the Money*.
