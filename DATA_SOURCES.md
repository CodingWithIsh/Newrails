# Data sources

Every source is free, needs no account or key, and was checked with a test pull on **26 October 2026** before the plan relied on it. Raw pulls are cached in `data/raw/` (git-ignored) with timestamps; `data/raw/MANIFEST.csv` records each file's SHA-256.

## Changes from the original brief

| Brief said | Changed to | Reason |
|---|---|---|
| "Download RPW from the World Bank site" | `datacatalogfiles.worldbank.org/ddh-published/0037898/DR0095523/rpw_dataset_2011_2025_q3.xlsx` | remittanceprices.worldbank.org returns 403 to scripts; the Data Catalog hosts the same file. Q3 2025 is still the latest release. |
| Price risk from CoinGecko | Binance public data (`data.binance.vision`) 1-minute candles | CoinGecko's free tier limits history to the past year at coarse resolution. Binance publishes monthly files with checksums. |
| "Stablecoin networks: choose two" | Tron (USDT) and Solana (USDC) | See PLAN.md §4. Base was considered and set aside. |
| Ramp fees from fee schedules only | Fee schedules **plus** live order books | Spreads, not fees, dominate cash-out, and spreads are only visible in order books. |

*The full source table is completed at step S10.*
