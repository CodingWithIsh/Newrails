"""Compute every result from data/cache and write results/*.csv (offline, deterministic).

`build()` returns a dict of tables; `plots.py` draws from the same dict, so a number in a chart is
always the number in results/summary.csv.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from plumbing import cost_model as cm
from plumbing import ingest_chain, ingest_rpw, risk
from plumbing.config import (
    CACHE,
    CORRIDORS,
    CORRIDORS_GBP,
    FEE_WINDOW,
    HEADLINE_HORIZON_MIN,
    RESULTS,
    SEND_GBP,
    VAR_HORIZONS_MIN,
    VAR_LEVELS,
)
from plumbing.ingest_prices import local_premium
from plumbing.ingest_ramps import fee_lookup, load_fees

log = logging.getLogger(__name__)

N_DRAWS = 2000
AMOUNT_CURVE = (50.0, 100.0, 150.0, 200.0, 300.0, 500.0, 1000.0)
SPEED_MIDPOINT_H = {"Less than one hour": 0.5}


def _read(name: str, cache: Path) -> pd.DataFrame:
    return pd.read_parquet(cache / name)


# ------------------------------------------------------------------ cost


def benchmarks(rpw: pd.DataFrame, amount: float = SEND_GBP) -> pd.DataFrame:
    return pd.DataFrame([ingest_rpw.benchmarks(rpw, c, amount) for c in CORRIDORS])


def wise_benchmarks(wise: pd.DataFrame, amount: float = 200.0) -> pd.DataFrame:
    """Same-day traditional benchmark: cost = fee / amount + Wise's markup estimate, per provider,
    median over pulls; then the cheapest (W1) and median (W2) provider per corridor."""
    w = wise[(wise["send_amount"] == amount)].copy()
    w["cost_pct"] = w["fee"] / w["send_amount"] * 100 + w["markup_pct"]
    per = w.groupby(["send_ccy", "recv_ccy", "provider", "provider_type"])["cost_pct"].median().reset_index()
    out = per.groupby(["send_ccy", "recv_ccy"]).agg(
        W1=("cost_pct", "min"), W2=("cost_pct", "median"), n_providers=("provider", "nunique")).reset_index()
    cheapest = per.loc[per.groupby(["send_ccy", "recv_ccy"])["cost_pct"].idxmin(), ["send_ccy", "recv_ccy", "provider"]]
    return out.merge(cheapest.rename(columns={"provider": "W1_provider"}), on=["send_ccy", "recv_ccy"])


def route_costs(books: pd.DataFrame, wise: pd.DataFrame, rpw: pd.DataFrame, amount: float = SEND_GBP,
                n: int = N_DRAWS) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    rounds = cm.snapshot_rounds(books, wise)
    fees = fee_lookup(load_fees())
    rows, draws = [], {}
    for route in cm.routes():
        bench = ingest_rpw.benchmarks(rpw, route.corridor, amount)
        d = cm.monte_carlo(route, rounds, fees, amount, n=n)
        if d.empty:
            continue
        draws[route.key] = d
        rows.append(cm.summarise(route, d, bench) | {"B1": bench["B1"], "B2": bench["B2"], "B3": bench["B3"],
                                                    "amount": amount, "send_ccy": route.corridor.send_ccy})
    return pd.DataFrame(rows), draws


def best_routes(costs: pd.DataFrame) -> pd.DataFrame:
    """For each corridor and rail, the route with the lowest median cost excluding the premium."""
    idx = costs.groupby(["corridor", "asset"])["ex_premium_p50"].idxmin()
    return costs.loc[idx].reset_index(drop=True)


def side_split(route: cm.Route, rounds: dict, amount: float) -> dict[str, float]:
    """On-ramp-side vs off-ramp-side cost (%, excluding premium and tax) at midpoint fees, median round."""
    fees = cm.draw_fees(cm.fee_ranges(route, fee_lookup(load_fees())), None, include_tax=False)
    needed = {route.on_book, route.off_book, route.swap_book} - {None}
    usable = sorted(k for k, v in rounds.items() if needed <= set(v["books"]))
    res = cm.evaluate(route, rounds[usable[len(usable) // 2]], amount, fees)
    on_names = ("deposit", "withdrawal", "on-ramp")
    on = np.prod([lg.factor for lg in res.legs if lg.name.startswith(on_names) and lg.category != "premium"])
    off = np.prod([lg.factor for lg in res.legs if not lg.name.startswith(on_names)
                   and lg.category not in ("premium", "tax") and not lg.name.startswith("official")])
    fixed = amount * (1 - np.prod([lg.factor for lg in res.legs if "fee" in lg.name and
                                   ("withdrawal" in lg.name or "deposit" in lg.name or "payout" in lg.name)]))
    return {"on_pct": 100 * (1 - on), "off_pct": 100 * (1 - off), "fixed_send": fixed}


def amount_curve(books: pd.DataFrame, wise: pd.DataFrame, rpw: pd.DataFrame, routes_: list[cm.Route]) -> pd.DataFrame:
    rounds = cm.snapshot_rounds(books, wise)
    fees = fee_lookup(load_fees())
    rows = []
    for a in AMOUNT_CURVE:
        for r in routes_:
            d = cm.monte_carlo(r, rounds, fees, a, n=400, include_tax=False)
            if not d.empty:
                rows.append({"amount": a, "corridor": r.corridor.key, "series": r.rail,
                             "cost_p50": d["cost_ex_premium"].median()})
        for c in CORRIDORS_GBP:
            q = ingest_rpw.interpolate(ingest_rpw.corridor_quotes(rpw, c), a)
            dig = q[ingest_rpw.is_digital_to_account(q)]
            rows.append({"amount": a, "corridor": c.key, "series": "Bank/MTO: median digital (RPW)",
                         "cost_p50": dig["total"].median()})
        w = wise[(wise["send_amount"] == a) & (wise["send_ccy"] == "GBP")].copy()
        if len(w):
            w["cost_pct"] = w["fee"] / a * 100 + w["markup_pct"]
            for (_, recv), g in w.groupby(["send_ccy", "recv_ccy"]):
                key = next((c.key for c in CORRIDORS_GBP if c.recv_ccy == recv), None)
                if key:
                    per = g.groupby("provider")["cost_pct"].median()
                    rows.append({"amount": a, "corridor": key, "series": "Bank/MTO: cheapest quote (Wise, Oct 2026)",
                                 "cost_p50": per.min()})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ speed


def speed(rpw: pd.DataFrame, cache: Path) -> dict[str, pd.DataFrame]:
    xrpl = _read("xrpl_live_intervals.parquet", cache)["interval_s"].dropna()
    spans = _read("xrpl_span_intervals.parquet", cache)["mean_interval_s"]
    sol = _read("solana_live.parquet", cache)
    slot_s = _read("solana_slot_seconds.parquet", cache)["slot_s"].median()
    tron = _read("tron_live.parquet", cache)
    tron_int = ingest_chain.tron_block_intervals(tron)

    def row(name: str, s: pd.Series, what: str, n: int | None = None) -> dict[str, Any]:
        return {"measure": name, "what": what, "n": n or int(s.count()), "median_s": s.median(),
                "p95_s": s.quantile(0.95), "p99_s": s.quantile(0.99), "max_s": s.max()}

    onchain = pd.DataFrame([
        row("XRPL ledger interval (live stream)", xrpl, "seconds between validated ledgers; a payment is final in its ledger"),
        row("XRPL mean interval per 100 ledgers (history)", spans, "Oct 2024-Sep 2026, stratified sample"),
        row("Solana finality lag (live, after Alpenglow)", sol["lag_finalized"] * slot_s, "processed -> finalized slot, x seconds per slot"),
        row("Solana slot time", pd.Series([slot_s] * 1), "node performance samples", n=len(sol)),
        row("Tron block interval (live)", tron_int, "seconds between consecutive blocks"),
        row("Tron solidification lag (live)", tron["lag_s"], "head block -> irreversible (19 confirmations)"),
    ])
    bands = pd.concat([ingest_rpw.speed_distribution(rpw, c) for c in CORRIDORS], axis=1).T
    return {"onchain": onchain, "rpw_speed": bands.reset_index().rename(columns={"index": "corridor"})}


# ------------------------------------------------------------------ risk


def xrp_risk(cache: Path) -> dict[str, pd.DataFrame]:
    x = _read("xrp_usdt_1m.parquet", cache)
    out = {"var": risk.var_table(x["close"], x["ts"], VAR_HORIZONS_MIN, VAR_LEVELS)}
    out["var_by_year"] = risk.var_by_group(x["close"], x["ts"], HEADLINE_HORIZON_MIN, 0.99, "year")
    out["var_by_regime"] = risk.var_by_group(x["close"], x["ts"], HEADLINE_HORIZON_MIN, 0.99, "vol_regime")
    out["backtest"] = pd.DataFrame([risk.backtest(x["close"], HEADLINE_HORIZON_MIN, 0.99, 30)])
    out["returns_10m"] = pd.DataFrame({"r": risk.horizon_returns(x["close"], HEADLINE_HORIZON_MIN)})
    return out


def peg(cache: Path) -> dict[str, pd.DataFrame]:
    h = _read("peg_1h.parquet", cache)
    m = _read("peg_1m_episodes.parquet", cache)
    return {"bands": risk.peg_bands(h), "episodes": _read("peg_episodes.parquet", cache),
            "recovery": risk.episode_recovery(m), "bad_prints": _read("peg_bad_prints.parquet", cache),
            "hourly": h, "minutes": m}


def network_fees(cache: Path, fx: pd.DataFrame) -> dict[str, pd.DataFrame]:
    native = _read("native_daily.parquet", cache)
    gbpusd = fx[(fx["base"] == "USD") & (fx["quote"] == "GBP") & (fx["source"] == "ecb")].assign(rate=lambda d: 1 / d["rate"])
    chain = _read("chain_fee_sample.parquet", cache)
    xrpl = _read("xrpl_tx_sample.parquet", cache)
    xrpl = xrpl[xrpl["xrp_payment"]].assign(time=lambda d: d["close_time"], fee_native=lambda d: d["fee_drops"] / 1e6)
    sol = chain[(chain["chain"] == "solana") & (chain["tx_kind"] == "usdc_only")].copy()
    tron = chain[(chain["chain"] == "tron") & (chain["tx_kind"] == "usdt") & ~chain["failed"]].copy()
    xrpl["gbp"] = risk.to_gbp(xrpl, native, gbpusd, "XRPUSDT")
    sol["gbp"] = risk.to_gbp(sol, native, gbpusd, "SOLUSDT")
    tron["gbp"] = risk.to_gbp(tron, native, gbpusd, "TRXUSDT")
    burned = tron[tron["energy_burned_sun"] > 0]
    rows = []
    for name, s in (("XRPL: XRP payment", xrpl["gbp"]), ("Solana: USDC transfer", sol["gbp"]),
                    ("Tron: USDT transfer, all", tron["gbp"]), ("Tron: USDT transfer, energy burned", burned["gbp"])):
        rows.append({"network": name, **risk.fee_tails(s.dropna()).iloc[0].to_dict()})
    monthly = pd.concat([
        s.groupby(df["time"].dt.tz_convert(None).dt.to_period("M")).median().rename(name)
        for name, s, df in (("XRPL", xrpl["gbp"], xrpl), ("Solana (USDC)", sol["gbp"], sol),
                            ("Tron (USDT, burned)", burned["gbp"], burned))], axis=1)
    return {"tails": pd.DataFrame(rows), "monthly_median": monthly,
            "tron_prices": _read("tron_resource_prices.parquet", cache),
            "tron_burn_share": pd.DataFrame([{"share_burning": float((tron["energy_burned_sun"] > 0).mean()),
                                              "n": len(tron)}])}


# ------------------------------------------------------------------ local premium history


PREMIUM_MARKETS = {"wazirx:usdtinr": "INR", "coindcx:I-USDT_INR": "INR", "quidax:usdtngn": "NGN",
                   "coinsph:USDTPHP": "PHP", "bitso:usdt_mxn": "MXN"}


def premium_history(cache: Path, fx: pd.DataFrame) -> pd.DataFrame:
    local = _read("local_usdt_daily.parquet", cache)
    out = []
    for market, ccy in PREMIUM_MARKETS.items():
        part = local[local["market"] == market]
        for source in ("ecb", "fawazahmed0", "rpw_interbank"):
            f = fx[fx["source"] == source]
            if not len(f[(f["quote"] == ccy)]):
                continue
            p = local_premium(part, f, ccy)
            if source == "rpw_interbank":
                p = p[p["date"].isin(f.loc[f["quote"] == ccy, "date"])]
            out.append(p.assign(market=market, quote=ccy, fx_source=source)[
                ["date", "market", "quote", "fx_source", "close", "rate", "premium"]])
    return pd.concat(out, ignore_index=True)


def snapshot_premium(books: pd.DataFrame, wise: pd.DataFrame) -> pd.DataFrame:
    rounds = cm.snapshot_rounds(books, wise)
    rows = []
    for rnd, v in rounds.items():
        for key, ccy in (("coindcx:I-USDT_INR", "INR"), ("luno:USDTNGN", "NGN"), ("quidax:usdtngn", "NGN"),
                         ("luno:USDTKES", "KES"), ("coinsph:USDTPHP", "PHP"), ("bitso:usdt_mxn", "MXN")):
            if key in v["books"] and ("USD", ccy) in v["fx"]:
                rows.append({"round": rnd, "market": key, "quote": ccy,
                             "premium": v["books"][key].mid / v["fx"][("USD", ccy)] - 1})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ hypotheses and summary


def hypotheses(costs: pd.DataFrame, rpw_bench: pd.DataFrame, fees: dict, spd: dict, xrisk: dict,
               pegs: dict, prem_snap: pd.DataFrame) -> pd.DataFrame:
    gbp = costs[(costs["send_ccy"] == "GBP")]
    best = best_routes(gbp)
    rows = []
    # H1: conversion cost of stablecoin rails >= B1's FX margin in >= 3 of 4 measurable GBP corridors
    b1m = rpw_bench.set_index("corridor")["B1_margin"]
    stab = best[best["asset"].isin(["USDT", "USDC"])].copy()
    stab["conv"] = stab["spread_p50"] + stab["fx_p50"]
    by_c = stab.groupby("corridor")["conv"].min()
    held = int((by_c >= b1m.reindex(by_c.index)).sum())
    rows.append({"id": "H1", "claim": "Stablecoin conversion cost >= cheapest provider's FX margin (>= 3 of 4 corridors)",
                 "result": f"{held} of {len(by_c)} corridors", "held": held >= 3})
    # H2: protocol fee < 0.05% of £200 on XRPL and Solana; >= 0.5% on Tron when burned; charged >= 10x protocol somewhere
    t = fees["tails"].set_index("network")["p50"]
    p_x, p_s, p_t = (t["XRPL: XRP payment"] / 200 * 100, t["Solana: USDC transfer"] / 200 * 100,
                     t["Tron: USDT transfer, energy burned"] / 200 * 100)
    ratio = 1.0323 * 0.747 / t["Solana: USDC transfer"]
    h2 = p_x < 0.05 and p_s < 0.05 and p_t >= 0.5 and ratio >= 10
    rows.append({"id": "H2", "claim": "Protocol fees tiny on XRPL/Solana, >= 0.5% on Tron when burned; charged >= 10x protocol",
                 "result": f"XRPL {p_x:.4f}%, Solana {p_s:.4f}%, Tron burned {p_t:.2f}%; Kraken USDC-Solana fee = {ratio:,.0f}x protocol",
                 "held": bool(h2)})
    # H3: median on-chain finality < 10 s (XRPL, Solana) and < 2 min (Tron); end-to-end > RPW median
    o = spd["onchain"].set_index("measure")["median_s"]
    x_fin = 2 * o["XRPL ledger interval (live stream)"]
    s_fin = o["Solana finality lag (live, after Alpenglow)"]
    t_fin = o["Tron solidification lag (live)"]
    rows.append({"id": "H3", "claim": "On-chain finality: < 10 s XRPL & Solana, < 2 min Tron; end-to-end slower than RPW median",
                 "result": f"XRPL ~{x_fin:.1f} s (two ledgers), Solana {s_fin:.2f} s, Tron {t_fin:.0f} s; "
                           "first-time UK buyer faces a 24 h FCA cooling-off vs RPW median 'less than one hour'",
                 "held": bool(x_fin < 10 and s_fin < 10 and t_fin < 120)})
    # H4: XRP 99% 10-min VaR > XRP rail's saving vs B1 in most corridors
    v = xrisk["var"]
    var10 = float(v[(v["horizon_min"] == HEADLINE_HORIZON_MIN) & (v["level"] == 0.99)]["var_pct"].iloc[0])
    xrp = best[best["asset"] == "XRP"].copy()
    xrp["saving"] = xrp["B1"] - xrp["cost_p50"]
    n_var_bigger = int((var10 > xrp["saving"]).sum())
    rows.append({"id": "H4", "claim": "XRP 99% 10-min VaR exceeds the XRP rail's saving vs B1 in most corridors",
                 "result": f"VaR {var10:.2f}%; larger than the saving in {n_var_bigger} of {len(xrp)} corridors "
                           "(savings exist only where a local premium pays the recipient)",
                 "held": n_var_bigger > len(xrp) / 2})
    # H5: > 99% of hours within ±0.5%; worst USDC episode > 5%
    b = pegs["bands"].set_index("pair")
    within = 1 - b["share_beyond_50bp"]
    worst_usdc = 1 - b.loc["usdcusd", "worst_close"]
    rows.append({"id": "H5", "claim": "Stablecoins within ±0.5% of $1 in > 99% of hours; worst USDC episode > 5%",
                 "result": f"USDC {100 * within['usdcusd']:.2f}%, USDT {100 * within['usdtusd']:.2f}% of hours; "
                           f"worst USDC hourly close ${b.loc['usdcusd', 'worst_close']:.3f}",
                 "held": bool((within > 0.99).all() and worst_usdc > 0.05),
                 "note": "Reported over all hours: 'outside episodes' would be circular because episodes are defined by the 0.5% band."})
    # H6: premium (India, Kenya) larger than the cost difference between rails, and varies > 2 pp over the window
    snap = prem_snap.groupby("market")["premium"].median() * 100
    spread_rails = best.groupby("corridor")["ex_premium_p50"].agg(lambda s: s.max() - s.min())
    ind, ken = snap.get("coindcx:I-USDT_INR", np.nan), snap.get("luno:USDTKES", np.nan)
    rows.append({"id": "H6", "claim": "Local premium (India, Kenya) exceeds the difference between rails and varies > 2 pp",
                 "result": f"premium India {ind:.1f}%, Kenya {ken:.1f}% vs rail differences "
                           f"{spread_rails.get('GBR-IND', np.nan):.1f} and {spread_rails.get('GBR-KEN', np.nan):.1f} pp; "
                           "time variation in premium_history",
                 "held": bool(ind > spread_rails.get("GBR-IND", np.inf) and ken > spread_rails.get("GBR-KEN", np.inf))})
    return pd.DataFrame(rows)


def tidy_summary(costs: pd.DataFrame, rpw_bench: pd.DataFrame, wise_bench: pd.DataFrame, spd: dict,
                 xrisk: dict, pegs: dict, fees: dict) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(section, corridor, rail, metric, est, lo=np.nan, hi=np.nan, unit="%", method="", n=np.nan):
        rows.append({"section": section, "corridor": corridor, "rail": rail, "metric": metric, "estimate": est,
                     "low": lo, "high": hi, "unit": unit, "method": method, "n": n})

    for r in best_routes(costs).itertuples():
        add("cost", r.corridor, r.rail, "all-in cost (incl. local premium and tax)", r.cost_p50, r.cost_p05, r.cost_p95,
            method=f"Monte Carlo over snapshots and fee ranges; route {r.onramp}->{r.offramp}", n=r.n_draws)
        add("cost", r.corridor, r.rail, "cost excluding local premium and tax", r.ex_premium_p50, r.ex_premium_p05,
            r.ex_premium_p95, method="as above, premium and tax legs removed", n=r.n_draws)
        add("cost", r.corridor, r.rail, "share of cost in exchange rates (excl. premium)", 100 * r.fx_share_p50,
            method="(spread + fx) / (fee + spread + fx), median draw")
        add("cost", r.corridor, r.rail, "P(beats cheapest digital provider, B1)", 100 * r.P_beats_B1)
        add("cost", r.corridor, r.rail, "P(beats median digital provider, B2)", 100 * r.P_beats_B2)
    for b in rpw_bench.itertuples():
        add("benchmark", b.corridor, "Bank/MTO", "B1 cheapest digital-to-account (RPW Q3 2025, £200 interpolated)", b.B1,
            method=f"{b.B1_firm}", n=b.n_digital)
        add("benchmark", b.corridor, "Bank/MTO", "B2 median digital-to-account", b.B2, n=b.n_digital)
        add("benchmark", b.corridor, "Bank/MTO", "B3 corridor average", b.B3, n=b.n_services)
        add("benchmark", b.corridor, "Bank/MTO", "share of cost in exchange rate (B3)", 100 * b.share_margin_B3)
    for w in wise_bench.itertuples():
        add("benchmark", f"{w.send_ccy}->{w.recv_ccy}", "Bank/MTO", "W1 cheapest quote (Wise comparison, Oct 2026)", w.W1,
            method=w.W1_provider, n=w.n_providers)
        add("benchmark", f"{w.send_ccy}->{w.recv_ccy}", "Bank/MTO", "W2 median quote (Wise comparison)", w.W2, n=w.n_providers)
    for s in spd["onchain"].itertuples():
        add("speed", "", s.measure.split(" ")[0], s.measure, s.median_s, s.p95_s, s.p99_s, unit="seconds",
            method="median (low=p95, high=p99)", n=s.n)
    v = xrisk["var"]
    for r in v.itertuples():
        add("risk", "", "XRP (XRPL)", f"VaR {int(100 * r.level)}% over {r.horizon_min} min on £200", r.var_gbp,
            200 * r.var_lo_pct / 100, 200 * r.var_hi_pct / 100, unit="GBP", method="historical simulation; 90% block-bootstrap CI",
            n=r.n)
        add("risk", "", "XRP (XRPL)", f"ES {int(100 * r.level)}% over {r.horizon_min} min on £200", r.es_gbp, unit="GBP", n=r.n)
    bt = xrisk["backtest"].iloc[0]
    add("risk", "", "XRP (XRPL)", "Kupiec backtest p-value (30-day rolling VaR 99%, 10 min)", bt.kupiec_p,
        unit="p", method=f"{int(bt.exceedances)} exceedances vs {bt.expected:.0f} expected", n=bt.tests)
    for b in pegs["bands"].itertuples():
        for band in (10, 50, 100):
            add("risk", "", b.pair,
                f"share of hours beyond {band} bp from $1", 100 * getattr(b, f"share_beyond_{band}bp"),
                method="Bitstamp hourly closes", n=b.hours)
        add("risk", "", b.pair, "worst hourly close", b.worst_close, unit="USD")
    for f in fees["tails"].itertuples():
        add("fees", "", f.network, "protocol fee per transfer (median; low=p99, high=max)", f.p50, f.p99, f.max, unit="GBP",
            method="stratified random blocks, Oct 2024-Sep 2026", n=f.n)
    return pd.DataFrame(rows)


def build(cache: Path = CACHE, out: Path = RESULTS, n_draws: int = N_DRAWS) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    rpw = ingest_rpw.load(cache / "rpw_q3_2025.parquet")
    books, wise = _read("ramp_books.parquet", cache), _read("wise_quotes.parquet", cache)
    fx = _read("fx_daily.parquet", cache)
    res: dict[str, Any] = {}
    res["rpw_bench"] = benchmarks(rpw)
    res["wise_bench"] = wise_benchmarks(wise)
    res["costs"], res["draws"] = route_costs(books, wise, rpw, n=n_draws)
    res["best"] = best_routes(res["costs"])
    rounds = cm.snapshot_rounds(books, wise)
    kraken = [r for r in cm.routes() if r.onramp == "kraken" and r.corridor.send_ccy == "GBP"]
    res["sides"] = pd.DataFrame([{"route": r.key, "corridor": r.corridor.key, "rail": r.rail, **side_split(r, rounds, SEND_GBP)}
                                 for r in kraken])
    best_kraken = [r for r in kraken if r.key in set(res["costs"].loc[res["costs"].onramp == "kraken"]
                                                      .sort_values("ex_premium_p50").groupby(["corridor", "asset"]).head(1)["route"])]
    res["amount_curve"] = amount_curve(books, wise, rpw, best_kraken)
    res["speed"] = speed(rpw, cache)
    res["xrp_risk"] = xrp_risk(cache)
    res["peg"] = peg(cache)
    res["fees"] = network_fees(cache, fx)
    res["premium_history"] = premium_history(cache, fx)
    res["premium_snapshots"] = snapshot_premium(books, wise)
    res["collection"] = _read("collection_log.parquet", cache)
    res["hypotheses"] = hypotheses(res["costs"], res["rpw_bench"], res["fees"], res["speed"], res["xrp_risk"],
                                   res["peg"], res["premium_snapshots"])
    res["summary"] = tidy_summary(res["costs"], res["rpw_bench"], res["wise_bench"], res["speed"], res["xrp_risk"],
                                  res["peg"], res["fees"])
    res["windows"] = pd.DataFrame([{
        "ramp_snapshots_from": books["ts"].min(), "ramp_snapshots_to": books["ts"].max(), "rounds": len(rounds),
        "fee_window": f"{FEE_WINDOW[0]}..{FEE_WINDOW[1]}",
        "requests_ok_share": res["collection"]["ok"].mean()}])

    res["summary"].to_csv(out / "summary.csv", index=False, float_format="%.4f")
    for name in ("rpw_bench", "wise_bench", "costs", "best", "sides", "amount_curve", "hypotheses", "windows",
                 "premium_snapshots"):
        res[name].to_csv(out / f"{name}.csv", index=False, float_format="%.4f")
    for name, df in res["speed"].items():
        df.to_csv(out / f"speed_{name}.csv", index=False, float_format="%.4f")
    for name in ("var", "var_by_year", "var_by_regime", "backtest"):
        res["xrp_risk"][name].to_csv(out / f"xrp_{name}.csv", index=False, float_format="%.4f")
    for name in ("bands", "episodes", "recovery", "bad_prints"):
        res["peg"][name].to_csv(out / f"peg_{name}.csv", index=False, float_format="%.5f")
    res["fees"]["tails"].to_csv(out / "network_fee_tails.csv", index=False, float_format="%.6f")
    res["fees"]["monthly_median"].to_csv(out / "network_fee_monthly.csv", float_format="%.6f")
    return res
