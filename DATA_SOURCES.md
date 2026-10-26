# Data sources

Every source is free and needs no account or API key. Each was checked with a test pull on **26 October 2026** before the plan relied on it. Raw responses are cached in `data/raw/` (git-ignored), each in an envelope recording URL, parameters and pull time. `data/raw/MANIFEST.csv` (committed) lists each file's size and SHA-256. `data/cache/` (committed) holds the compact tables every result is built from.

## Sources

| Source | What it gives | Access and limits | Window | Cache file |
|---|---|---|---|---|
| World Bank, Remittance Prices Worldwide, `rpw_dataset_2011_2025_q3.xlsx` (datacatalogfiles.worldbank.org/ddh-published/0037898/DR0095523/) | Bank/MTO prices at £120/£300 and $200/$500; `speed actual`; interbank rates | Download, CC BY 4.0. remittanceprices.worldbank.org returns 403 to scripts; the Data Catalog hosts the same file. SHA-256 `f1d7265b…2d2a8`. | Q3 2025 (collected 8–26 Aug 2025) | `rpw_q3_2025.parquet` |
| Wise comparison API (`api.wise.com/v4/comparisons`) | Same-day quotes from 3–18 providers per corridor at any amount, plus Wise's mid-market rate | Public, no key; polled once per 10 minutes per pair at 1 request/s | From 26 Oct 2026 | `wise_quotes.parquet` |
| Order books: Kraken, Coinbase Exchange, Bitstamp, CoinDCX, WazirX, Luno, Quidax, Coins.ph, Bitso (public REST) | On- and off-ramp prices and depth (top 100 levels) | Public; 33 books every 10 minutes | From 26 Oct 2026 | `ramp_books.parquet`, `collection_log.parquet` |
| Binance public data (`data.binance.vision`) | XRPUSDT 1-minute candles | Monthly zips, each verified against its published SHA-256. Timestamps switch from ms to µs in January 2025. | Jan 2021 – Sep 2026 | `xrp_usdt_1m.parquet` |
| Binance REST (`api.binance.com/api/v3/klines`) | Daily XRP, TRX and SOL prices (to price network fees) | Public | 2021 – Oct 2026 | `native_daily.parquet` |
| Bitstamp OHLC (`/api/v2/ohlc/`) | USDC/USD and USDT/USD hourly (peg); minutes around episodes; XRP/GBP minutes (staleness check) | Public, 1,000 candles per call, 0.5 s pacing. USDT/USD starts 10 Jun 2021. | 2021 – Sep 2026 | `peg_1h`, `peg_1m_episodes`, `peg_episodes`, `peg_bad_prints`, `xrp_gbp_1m_bitstamp_2026_09` |
| Frankfurter (ECB reference rates) | Official USD→INR, PHP, MXN, GBP | Public | Dec 2020 – Oct 2026 | `fx_daily.parquet` (source `ecb`) |
| fawazahmed0 currency-api (jsDelivr) | Daily USD→NGN, KES, PKR (and others) | Public; daily files from 2 Mar 2024 only | Mar 2024 – Oct 2026 | `fx_daily.parquet` (source `fawazahmed0`) |
| RPW interbank rates (US-sender corridors) | Quarterly official anchors | Excludes US-dollar payouts: Nigeria paid recipients in USD until 2024 | 2021 – 2025 | `fx_daily.parquet` (source `rpw_interbank`) |
| Local exchange daily candles: WazirX (2021–), CoinDCX (last 1,000 days), Quidax (2021–), Coins.ph (from Jan 2024), Bitso (from 2024) | USDT price history for the local premium | Public. Luno candles need a key, so Kenya uses snapshots only. | as listed | `local_usdt_daily.parquet` |
| XRPL public servers (s2.ripple.com full history, xrplcluster.com, s1.ripple.com) | 480 stratified ledgers (fees), 504 100-ledger spans (intervals), live `ledgerClosed` stream (about 3 h) | JSON-RPC and WebSocket, 0.25 s pacing, automatic fallback between servers | Oct 2024 – Sep 2026; live 26 Oct 2026 | `xrpl_tx_sample`, `xrpl_span_intervals`, `xrpl_live_intervals` |
| Solana public RPC (`api.mainnet-beta.solana.com`) | 120 stratified blocks (fees, `transactionDetails: accounts`); live slot and finality (batched `getSlot`) for 2 h | Public, about 100 requests per 10 s; version-1 transactions require `maxSupportedTransactionVersion: 1` | Oct 2024 – Sep 2026; live 26 Oct 2026 (after Alpenglow) | `chain_fee_sample`, `solana_live`, `solana_slot_seconds` |
| TronGrid (`api.trongrid.io`) | 480 stratified blocks of receipts (USDT energy and burn); energy and bandwidth price history; live head and solidified blocks for 2 h | Public without a key (rate-limited); 0.4 s pacing | 2018 – Oct 2026 (prices); Oct 2024 – Sep 2026 (sample) | `chain_fee_sample`, `tron_resource_prices`, `tron_live` |
| FSB, *G20 Roadmap for Cross-border Payments: Consolidated progress report for 2025* (fsb.org/uploads/P091025-1.pdf) | Published remittance and Swift speed KPIs | PDF | 2025 | cited in LIMITATIONS |
| Fee pages (Kraken, Coinbase, Revolut, Bitso, plus secondary sources for CoinDCX, Luno, Quidax and Coins.ph) | Trading, withdrawal and payout fees, as ranges | Read by hand on 26 Oct 2026; URL and date on every entry | as of 26 Oct 2026 | `data/manual/fees.yaml`, `availability.yaml` |

## Changes from the original brief

| Brief said | Changed to | Reason |
|---|---|---|
| "Download RPW from the World Bank site" | The World Bank Data Catalog copy of the same file | The RPW site blocks scripted downloads (HTTP 403). |
| Price risk from CoinGecko | Binance public data | CoinGecko's free tier limits history to the past year at coarse resolution. Binance publishes checksummed minute data. |
| "Stablecoin networks: choose two" | Tron (USDT) and Solana (USDC) | Destination markets trade USDT, mostly on Tron; Solana is the largest low-fee USDC network. Base was set aside (shallow fee history; few destination deposits seen). |
| Ramp fees from fee schedules only | Fee schedules **plus** live order books | Spreads, not fees, dominate cash-out, and only order books show them. |
| SWIFT gpi statistics for bank speed | RPW's own `speed actual` field, plus the FSB 2025 KPI report | RPW measures the same services that are priced. The FSB report carries Swift's speed figures. |

## Data that could not be collected automatically

- **CoinDCX fees** (coindcx.com/fees) and **Luno Nigeria and Kenya fees** (guide.luno.com.ng) are behind bot checks. They were not bypassed. Secondary sources were used and the entries are marked `verified: false`.
- **Coinbase Advanced fee tiers** are visible only when signed in, so they are entered as a range.
- **Pakistan:** no regulated venue publishes a PKR market. Binance P2P has no official API and was not scraped.
- **Solana finality before Alpenglow** cannot be measured retroactively. The first two minutes of the live sampler used sequential queries; that file is kept as `*_DISCARDED.jsonl.bak` and never read.

## Licences and terms

World Bank RPW: CC BY 4.0, attributed as "The World Bank, Remittance Prices Worldwide". Exchange and node data are used under each provider's public API terms, for non-commercial research. Check those terms before redistributing `data/cache/`.
