# Progress (updated 26 Oct 2026, 06:20 UTC)

## Done (all committed; 122 tests passing)
- S0–S5: plan and review (docs/plan_review.md, rounds 1–7), ingest modules for RPW, prices, ramps, XRPL and chains, and the data cache.
- S6: data/manual/fees.yaml (31 fees, 16 unverified) and data/manual/availability.yaml (37 route legs).
- S7: cost_model.py (order-book walking, leg decomposition, routes, Monte Carlo, closed-form breakeven).
- S8: risk.py (VaR/ES, block bootstrap, Kupiec, peg bands, fee tails).
- S9: report.py, plots.py (8 charts in results/figures), and `python -m plumbing run --all` (about 1 minute, offline).

## Still running
- The **ramp collector runs until about 29 Oct 02:20 UTC** (`pgrep -fl "plumbing collect"`). After it stops, re-run `python -m plumbing run --all`. That refreshes results from the full 72 hours. Then update the numbers quoted in writeup/article.md and writeup/cv_summary.md from results/summary.csv and results/hypotheses.csv.

## Next
1. notebooks/analysis.ipynb: tells the story with the 8 charts, calling report.build() and plots.
2. LIMITATIONS.md; finish ASSUMPTIONS.md (fees, Revolut XRP proxy, TDS, swaps, held-flat RPW) and DATA_SOURCES.md (full table).
3. writeup/article.md (1,200–1,500 words, voice of article 2) and writeup/cv_summary.md.
4. README.md, Makefile (setup/test/lint/all/refresh), requirements.lock, .github/workflows/ci.yml, coverage ≥ 85%, and a fresh-clone `make all` check.

## Pages that need a human (bot checks blocked automated reading)
- coindcx.com/fees, guide.luno.com.ng (Nigeria fees and limits), and the Luno Kenya fee page. If you read them, update the `unverified` entries in data/manual/fees.yaml and re-run.

## Headline results so far (provisional, about 30 snapshot rounds)
- Crypto routes: 0–30% of cost is exchange rate (vs 54% for traditional UK providers); fees dominate.
- Before any local premium, the newer rails rarely beat the cheapest digital provider (B1).
- India +6.3% and Kenya +3.6% USDT premiums make those routes look "negative cost". This is policy, not technology.
- XRP 99% 10-min VaR on £200 is £2.40 (1.20%). Kupiec rejects a 30-day rolling VaR (689 breaches vs 496 expected).
- H1, H2, H3, H5 and H6 held; H4 did not (2 of 4 corridors).
