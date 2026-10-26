# Progress (updated 26 Oct 2026, 06:20 UTC)

## Done (all committed; 122 tests passing)
- S0–S5: plan and review (docs/plan_review.md, rounds 1–7), ingest modules for RPW, prices, ramps, XRPL and chains, and the data cache.
- S6: data/manual/fees.yaml (31 fees, 16 unverified) and data/manual/availability.yaml (37 route legs).
- S7: cost_model.py (order-book walking, leg decomposition, routes, Monte Carlo, closed-form breakeven).
- S8: risk.py (VaR/ES, block bootstrap, Kupiec, peg bands, fee tails).
- S9: report.py, plots.py (8 charts in results/figures), and `python -m plumbing run --all` (about 1 minute, offline).

## Still running
- The **ramp collector runs until about 29 Oct 02:20 UTC** (`pgrep -fl "plumbing collect"`). After it stops, re-run `python -m plumbing run --all`. That refreshes results from the full 72 hours. Then update the numbers quoted in writeup/article.md and writeup/cv_summary.md from results/summary.csv and results/hypotheses.csv.

## Also done (06:20–06:40 UTC)
- notebooks/analysis.ipynb (executed), LIMITATIONS.md, ASSUMPTIONS.md (A1–A27), DATA_SOURCES.md, writeup/article.md, writeup/cv_summary.md, README.md, Makefile, requirements.lock, CI workflow, LICENSE (MIT).
- 131 tests, 95.5% coverage (network orchestration marked `pragma: no cover`), mypy clean, ruff clean.

## Next
1. Check that the fresh-clone `make setup && make all` test passed (scratchpad/clone_all.log), and fix anything it found.
2. After the collector stops (~29 Oct 02:20 UTC): `python -m plumbing run --all`, then `make notebook`, then refresh the numbers in article.md, cv_summary.md and README.md from results/best.csv, summary.csv and hypotheses.csv, and remove the "provisional" notes. Commit.
3. Trim article.md from ~1,570 to ≤1,500 words (the "How I did this" section can lose ~80 words).
4. Optional: write the raw-data MANIFEST (`python -m plumbing run --all` writes it), then push to GitHub (the user's action; the repo is local only).

## Pages that need a human (bot checks blocked automated reading)
- coindcx.com/fees, guide.luno.com.ng (Nigeria fees and limits), and the Luno Kenya fee page. If you read them, update the `unverified` entries in data/manual/fees.yaml and re-run.

## Headline results so far (provisional, about 30 snapshot rounds)
- Crypto routes: 0–30% of cost is exchange rate (vs 54% for traditional UK providers); fees dominate.
- Before any local premium, the newer rails rarely beat the cheapest digital provider (B1).
- India +6.3% and Kenya +3.6% USDT premiums make those routes look "negative cost". This is policy, not technology.
- XRP 99% 10-min VaR on £200 is £2.40 (1.20%). Kupiec rejects a 30-day rolling VaR (689 breaches vs 496 expected).
- H1, H2, H3, H5 and H6 held; H4 did not (2 of 4 corridors).
