"""The eight publication charts, drawn from the tables `report.build()` returns.

Static PNGs for Substack (light surface). Colours come from a validated categorical palette
(scripts/validate_palette.js: all checks pass; two slots sit below 3:1 contrast, so every series
is also direct-labelled or named in a legend, and results/summary.csv is the table view).
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from plumbing.config import FIGURES, SEND_GBP  # noqa: E402

SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, VIOLET, RED = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6", "#e34948"
CATEGORY = {"fee": BLUE, "exchange rate": ORANGE, "local premium": AQUA, "tax (TDS)": YELLOW}
RAIL = {"Bank/MTO": BLUE, "XRP (XRPL)": ORANGE, "USDT (Tron)": AQUA, "USDC (Solana)": YELLOW}
NAMES = {"GBR-IND": "UK → India", "GBR-NGA": "UK → Nigeria", "GBR-PHL": "UK → Philippines",
         "GBR-KEN": "UK → Kenya", "GBR-PAK": "UK → Pakistan", "USA-MEX": "US → Mexico"}
SOURCE = "Source: Numbers Behind the Money analysis"


def style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": AXIS, "axes.labelcolor": INK2,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "axes.spines.top": False, "axes.spines.right": False, "axes.titlesize": 11, "axes.titlecolor": INK,
        "axes.titleweight": "bold", "axes.titlelocation": "left", "legend.frameon": False, "legend.fontsize": 9,
        "lines.linewidth": 2, "text.parse_math": False,  # "$1" is money, not maths
    })


def _plain_log(ax: plt.Axes, axis: str = "x") -> None:
    """Log-axis tick labels as plain numbers (mathtext is off so '$' stays literal)."""
    fmt = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}")
    target = ax.xaxis if axis == "x" else ax.yaxis
    target.set_major_formatter(fmt)
    target.set_minor_formatter(matplotlib.ticker.NullFormatter())


def _wrap(fig: plt.Figure, text: str, fontsize: float) -> str:
    """Wrap to the figure width (about 0.55 em per character)."""
    chars = int(fig.get_figwidth() * 72 / (fontsize * 0.55) * 0.97)
    return "\n".join(textwrap.wrap(text, chars))


def _finish(fig: plt.Figure, title: str, subtitle: str, source: str, path: Path) -> Path:
    fig.suptitle(title, x=0.012, y=0.995, ha="left", va="top", fontsize=14, fontweight="bold", color=INK)
    fig.text(0.012, 0.945, _wrap(fig, subtitle, 10), ha="left", va="top", fontsize=10, color=INK2)
    fig.text(0.012, 0.006, _wrap(fig, source, 8), ha="left", va="bottom", fontsize=8, color=MUTED)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


# ------------------------------------------------------------------ 1. where your £200 goes


def fig_where(res: dict[str, Any], out: Path) -> Path:
    best = res["best"]
    best = best[best["send_ccy"] == "GBP"]
    rb = res["rpw_bench"].set_index("corridor")
    corridors = ["GBR-IND", "GBR-NGA", "GBR-PHL", "GBR-KEN"]
    fig, axes = plt.subplots(len(corridors) + 1, 1, figsize=(10, 11.5),
                             gridspec_kw={"height_ratios": [5] * len(corridors) + [1.2]})
    fig.subplots_adjust(left=0.27, right=0.97, top=0.86, bottom=0.07, hspace=0.45)
    for ax, c in zip(axes, corridors, strict=False):
        rows = []
        b = rb.loc[c]
        rows.append(("Cheapest bank/MTO (B1)", {"fee": b.B1_fee_pct, "exchange rate": b.B1_margin}))
        rows.append(("Median digital bank/MTO (B2)", {"fee": b.B2 - b.B2_margin, "exchange rate": b.B2_margin}))
        for rail in ("XRP (XRPL)", "USDT (Tron)", "USDC (Solana)"):
            r = best[(best.corridor == c) & (best.rail == rail)]
            if len(r):
                r = r.iloc[0]
                rows.append((f"{rail} via {r.onramp.title()}", {"fee": r.fee_p50, "exchange rate": r.spread_p50 + r.fx_p50,
                                                               "local premium": r.premium_p50, "tax (TDS)": r.tax_p50}))
        for i, (_label, parts) in enumerate(rows[::-1]):
            pos, neg = 0.0, 0.0
            for cat, v in parts.items():
                v = 2 * v  # % of £200 -> pounds
                if v >= 0:
                    ax.barh(i, v, left=pos, color=CATEGORY[cat], height=0.62, edgecolor=SURFACE, linewidth=1.5)
                    pos += v
                else:
                    ax.barh(i, v, left=neg, color=CATEGORY[cat], height=0.62, edgecolor=SURFACE, linewidth=1.5)
                    neg += v
            net = sum(2 * v for v in parts.values())
            label = f"net £{net:.2f}" if net >= 0 else f"net gain £{-net:.2f}"
            ax.text(max(pos, 0) + 0.15, i, label, va="center", fontsize=9, color=INK)
        ax.set_yticks(range(len(rows)), [r[0] for r in rows[::-1]], color=INK2)
        ax.axvline(0, color=AXIS, linewidth=1)
        ax.set_title(NAMES[c])
        ax.grid(axis="y", visible=False)
        ax.set_xlim(-15, 11)
        ax.set_xticks(range(-14, 11, 2), [f"−£{-t}" if t < 0 else f"£{t}" for t in range(-14, 11, 2)])
    axes[-1].axis("off")
    axes[-1].text(0.0, 0.5, "UK → Pakistan: no regulated exchange publishes a rupee market, so the newer rails\nhave no "
                  "cash-out leg to measure.", transform=axes[-1].transAxes, fontsize=9.5, color=INK2, va="center")
    axes[-2].set_xlabel("Cost of sending £200, in pounds (bars left of zero are gains for the recipient)")
    handles = [plt.Rectangle((0, 0), 1, 1, color=v) for v in CATEGORY.values()]
    fig.legend(handles, list(CATEGORY), ncol=4, loc="upper left", bbox_to_anchor=(0.27, 0.905))
    return _finish(fig, "Where your £200 goes",
                   "Newer rails shrink the exchange-rate margin but add fees; in India and Kenya a local USDT premium "
                   "pays the recipient, which is policy, not technology.",
                   f"{SOURCE}. Bank/MTO: World Bank RPW Q3 2025, interpolated to £200. Crypto: median of Monte Carlo over "
                   "order-book snapshots (Oct 2026) and published fees; cheapest route per rail.", out / "fig1_where_200_goes.png")


# ------------------------------------------------------------------ 2. cost vs benchmarks with ranges


def fig_costs(res: dict[str, Any], out: Path) -> Path:
    c = res["costs"]
    corridors = ["GBR-IND", "GBR-NGA", "GBR-PHL", "GBR-KEN", "USA-MEX"]
    fig, grid = plt.subplots(2, 3, figsize=(13.5, 10))
    fig.subplots_adjust(left=0.13, right=0.99, top=0.84, bottom=0.08, wspace=0.75, hspace=0.35)
    axes = grid.flat
    rb = res["rpw_bench"].set_index("corridor")
    for ax, cor in zip(axes, corridors, strict=False):
        part = c[c.corridor == cor].sort_values(["asset", "ex_premium_p50"])
        y = np.arange(len(part))
        for yi, r in zip(y, part.itertuples(), strict=True):
            col = RAIL[r.rail]
            ax.plot([r.ex_premium_p05, r.ex_premium_p95], [yi, yi], color=col, linewidth=2, alpha=0.9)
            ax.plot(r.ex_premium_p50, yi, "o", color=col, markersize=8, markeredgecolor=SURFACE, markeredgewidth=2)
            ax.plot(r.cost_p50, yi, "D", color=INK2, markersize=5, markerfacecolor="none")
        b = rb.loc[cor]
        for val, ls in ((b.B1, ":"), (b.B2, "--")):
            ax.axvline(val, color=INK2, linestyle=ls, linewidth=1.2)
        venue = {"luno_ng": "Luno", "luno_ke": "Luno", "coindcx": "CoinDCX", "coinsph": "Coins.ph", "quidax": "Quidax",
                 "bitso": "Bitso"}
        ax.set_yticks(y, [f"{r.asset} · {r.onramp.title()} → {venue.get(r.offramp, r.offramp)}" for r in part.itertuples()],
                      fontsize=8)
        ax.set_title(NAMES[cor], fontsize=10)
        ax.set_xlabel("cost, % of amount")
        ax.grid(axis="y", visible=False)
    handles = [plt.Line2D([], [], marker="o", linestyle="-", color=v, label=f"{k}: median, 5-95% range")
               for k, v in RAIL.items() if k != "Bank/MTO"]
    handles += [plt.Line2D([], [], marker="D", linestyle="", color=INK2, markerfacecolor="none",
                           label="all-in, incl. local premium & tax"),
                plt.Line2D([], [], color=INK2, linestyle=":", label="B1 cheapest digital bank/MTO"),
                plt.Line2D([], [], color=INK2, linestyle="--", label="B2 median digital bank/MTO")]
    grid.flat[-1].axis("off")
    grid.flat[-1].legend(handles=handles, loc="center left", fontsize=9)
    return _finish(fig, "Before any local premium, the newer rails rarely beat the cheapest provider",
                   "Dots: median cost excluding the local premium; lines: 5-95% range over snapshots and fee ranges. "
                   "£200 from the UK, $200 to Mexico.",
                   f"{SOURCE}. Benchmarks: World Bank RPW Q3 2025 (digital, delivered to an account).",
                   out / "fig2_cost_vs_benchmarks.png")


# ------------------------------------------------------------------ 3. local premium history


def fig_premium(res: dict[str, Any], out: Path) -> Path:
    ph = res["premium_history"]
    snap = res["premium_snapshots"]
    fig, ax = plt.subplots(figsize=(11, 5.8))
    fig.subplots_adjust(left=0.08, right=0.76, top=0.82, bottom=0.12)
    series = [("wazirx:usdtinr", "ecb", "India (WazirX)", ORANGE), ("quidax:usdtngn", "fawazahmed0", "Nigeria (Quidax)", BLUE),
              ("coinsph:USDTPHP", "ecb", "Philippines (Coins.ph)", AQUA), ("bitso:usdt_mxn", "ecb", "Mexico (Bitso)", YELLOW)]
    for market, src, label, col in series:
        s = ph[(ph.market == market) & (ph.fx_source == src)].sort_values("date")
        s = s.set_index("date")["premium"].rolling("7D").median() * 100
        ax.plot(s.index, s.values, color=col, linewidth=1.8)
        ax.text(s.index[-1] + pd.Timedelta(days=12), s.values[-1], label, color=INK2, fontsize=9, va="center")
    ng = ph[(ph.market == "quidax:usdtngn") & (ph.fx_source == "rpw_interbank")]
    ax.plot(ng["date"], ng["premium"] * 100, "o", color=BLUE, markersize=8, markeredgecolor=SURFACE, markeredgewidth=2)
    for _, r in ng.iterrows():
        ax.annotate(f"{100 * r.premium:.0f}%", (r.date, 100 * r.premium), xytext=(6, 4), textcoords="offset points",
                    fontsize=8, color=INK2)
    ke = snap[snap.market == "luno:USDTKES"]["premium"].median() * 100
    ax.plot(snap["round"].max(), ke, "s", color=MAGENTA, markersize=8)
    ax.text(snap["round"].max() + pd.Timedelta(days=12), ke, "Kenya (Luno, Oct 2026)", color=INK2, fontsize=9, va="center")
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.set_ylabel("USDT price vs official USD rate, %")
    ax.set_xlim(pd.Timestamp("2021-01-01"), pd.Timestamp("2027-01-01"))
    return _finish(fig, "Where capital is controlled, USDT sells above the official rate",
                   "Premium of the local USDT price over the official USD exchange rate, 7-day rolling median. Nigeria starts in "
                   "March 2024: until then almost every surveyed service paid recipients in dollars, so no official naira rate exists.",
                   f"{SOURCE}. Exchange daily candles; official rates: ECB (INR, PHP, MXN), fawazahmed0 currency-api "
                   "(NGN from Mar 2024), World Bank RPW interbank rates (NGN 2022-2025).", out / "fig3_local_premium.png")


# ------------------------------------------------------------------ 4. speed


def fig_speed(res: dict[str, Any], out: Path) -> Path:
    o = res["speed"]["onchain"].set_index("measure")
    rpw = res["speed"]["rpw_speed"].set_index("corridor")
    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 5.6), gridspec_kw={"width_ratios": [1.1, 1]})
    fig.subplots_adjust(left=0.22, right=0.98, top=0.80, bottom=0.22, wspace=0.6)
    rows = [("Solana finality (after Alpenglow)", "Solana finality lag (live, after Alpenglow)", YELLOW),
            ("XRPL ledger close", "XRPL ledger interval (live stream)", ORANGE),
            ("Tron irreversible", "Tron solidification lag (live)", AQUA)]
    for i, (_lab, key, col) in enumerate(rows):
        r = o.loc[key]
        a.plot([r.median_s, r.p99_s], [i, i], color=col, linewidth=2)
        a.plot(r.median_s, i, "o", color=col, markersize=9, markeredgecolor=SURFACE, markeredgewidth=2)
        a.text(r.p99_s * 1.15, i, f"median {r.median_s:.2g} s · p99 {r.p99_s:.2g} s", va="center", fontsize=8.5, color=INK2)
    a.set_xscale("log")
    a.set_xlim(0.1, 2000)
    _plain_log(a)
    a.set_yticks(range(len(rows)), [r[0] for r in rows], color=INK2)
    a.set_xlabel("seconds (log scale)")
    a.set_title("On-chain settlement, measured live")
    a.grid(axis="y", visible=False)
    cors = ["GBR-IND", "GBR-NGA", "GBR-PHL", "GBR-PAK", "GBR-KEN"]
    bands = [("Less than one hour", BLUE), ("Same day", ORANGE), ("Next day", AQUA), ("2 days", YELLOW),
             ("3-5 days", MAGENTA), ("6 days or more", VIOLET)]
    left = np.zeros(len(cors))
    for band, col in bands:
        v = rpw.loc[cors, band].to_numpy() * 100
        b.barh(range(len(cors)), v, left=left, color=col, height=0.6, edgecolor=SURFACE, linewidth=1.5, label=band)
        left += v
    b.set_yticks(range(len(cors)), [NAMES[c] for c in cors], color=INK2)
    b.set_xlabel("% of bank/MTO services")
    b.set_title("Banks and transfer firms, published speed")
    b.grid(axis="y", visible=False)
    b.legend(ncol=3, loc="upper left", bbox_to_anchor=(-0.45, -0.13), fontsize=8)
    return _finish(fig, "The ledger settles in seconds; the money still has to get on and off it",
                   "On-chain finality is seconds, but exchanges add withdrawal processing and deposit confirmations, and a "
                   "first-time UK buyer faces the FCA's 24-hour cooling-off period.",
                   f"{SOURCE}. Live sampling 26 Oct 2026 (XRPL ledger stream, Solana and Tron RPC); World Bank RPW Q3 2025 "
                   "'speed actual'.", out / "fig4_speed.png")


# ------------------------------------------------------------------ 5. XRP value-at-risk


def fig_var(res: dict[str, Any], out: Path) -> Path:
    v = res["xrp_risk"]["var"]
    reg = res["xrp_risk"]["var_by_regime"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 5.4), gridspec_kw={"width_ratios": [1.3, 1]})
    fig.subplots_adjust(left=0.07, right=0.97, top=0.80, bottom=0.13, wspace=0.3)
    for lvl, col in ((0.95, BLUE), (0.99, ORANGE)):
        s = v[v.level == lvl]
        a.fill_between(s.horizon_min, 2 * s.var_lo_pct, 2 * s.var_hi_pct, color=col, alpha=0.18, linewidth=0)
        a.plot(s.horizon_min, 2 * s.var_pct, "-o", color=col, markersize=7, markeredgecolor=SURFACE, markeredgewidth=2)
        last = s.iloc[-1]
        a.text(last.horizon_min * 1.05, 2 * last.var_pct, f"{int(lvl * 100)}% VaR", color=INK2, fontsize=9, va="center")
    h10 = v[(v.horizon_min == 10) & (v.level == 0.99)].iloc[0]
    a.annotate(f"10 minutes, 99%: £{h10.var_gbp:.2f}", (10, h10.var_gbp), xytext=(16, h10.var_gbp + 2.5),
               fontsize=9, color=INK, arrowprops={"arrowstyle": "-", "color": MUTED})
    a.set_xscale("log")
    a.set_xticks([1, 5, 10, 30, 60], ["1", "5", "10", "30", "60"])
    a.set_xlabel("minutes between buying XRP and selling it")
    a.set_ylabel("loss on £200 not exceeded, £")
    a.set_title("Value-at-risk by transfer time, 2021-2026")
    b.bar(range(len(reg)), 2 * reg.var_pct, color=ORANGE, width=0.6, edgecolor=SURFACE)
    for i, r in enumerate(reg.itertuples()):
        b.text(i, 2 * r.var_pct + 0.08, f"£{2 * r.var_pct:.2f}", ha="center", fontsize=8.5, color=INK)
    b.set_xticks(range(len(reg)), reg.vol_regime.astype(str), fontsize=8.5)
    b.set_title("10-minute 99% VaR by market mood")
    b.set_xlabel("quintile of the previous 24 hours' volatility")
    b.grid(axis="x", visible=False)
    bt = res["xrp_risk"]["backtest"].iloc[0]
    return _finish(fig, "Ten minutes holding XRP can cost more than the transfer fee",
                   f"Historical simulation on Binance XRP/USDT 1-minute prices; shaded: 90% block-bootstrap interval. "
                   f"A VaR fitted on the previous 30 days was beaten {int(bt.exceedances)} times vs {bt.expected:.0f} expected.",
                   f"{SOURCE}. Binance public data (checksummed monthly files), 1 Jan 2021 - 30 Sep 2026.",
                   out / "fig5_xrp_var.png")


# ------------------------------------------------------------------ 6. peg deviations


def fig_peg(res: dict[str, Any], out: Path) -> Path:
    h = res["peg"]["hourly"]
    m = res["peg"]["minutes"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(12.5, 5.4), gridspec_kw={"width_ratios": [1.6, 1]})
    fig.subplots_adjust(left=0.07, right=0.97, top=0.80, bottom=0.13, wspace=0.25)
    for pair, col, lab in (("usdcusd", BLUE, "USDC"), ("usdtusd", AQUA, "USDT")):
        s = h[h.pair == pair].set_index("ts")["close"]
        a.plot(s.index, (s - 1) * 1e4, color=col, linewidth=0.8, label=lab)
    a.set_yscale("symlog", linthresh=50)
    a.set_yticks([-1000, -100, -50, 0, 50, 100], ["-10%", "-1%", "-0.5%", "0", "+0.5%", "+1%"])
    a.axhspan(-50, 50, color=GRID, alpha=0.5, linewidth=0)
    a.set_ylabel("hourly close vs $1")
    a.set_title("Hourly closes, 2021-2026 (grey band: ±0.5%)")
    a.legend(loc="lower left")
    ep = m[(m.pair == "usdcusd") & (m.episode_start == m.loc[m[m.pair == "usdcusd"]["close"].idxmin(), "episode_start"])]
    b.plot(ep["ts"], ep["close"], color=BLUE, linewidth=1.2)
    lo = ep.loc[ep["close"].idxmin()]
    b.annotate(f"${lo.close:.3f}", (lo.ts, lo.close), xytext=(20, -5), textcoords="offset points", fontsize=9, color=INK)
    b.axhline(1, color=AXIS, linewidth=1)
    b.set_title("USDC, March 2023 (Silicon Valley Bank), minutes")
    b.tick_params(axis="x", rotation=30)
    bands = res["peg"]["bands"].set_index("pair")
    return _finish(fig, "Stablecoins hold $1 almost always, until they don't",
                   f"USDC was more than 0.5% from $1 in {100 * bands.loc['usdcusd', 'share_beyond_50bp']:.2f}% of hours "
                   f"and USDT in {100 * bands.loc['usdtusd', 'share_beyond_50bp']:.2f}%; the worst minute was USDC at ${lo.close:.2f}.",
                   f"{SOURCE}. Bitstamp USDC/USD and USDT/USD (fiat-quoted); impossible prints outside $0.50-$1.50 removed and counted.",
                   out / "fig6_peg.png")


# ------------------------------------------------------------------ 7. protocol fee vs charged fee


def fig_fees(res: dict[str, Any], out: Path) -> Path:
    t = res["fees"]["tails"].set_index("network")
    gbp_per_usd = 1 / 1.3385
    rows = [
        ("XRP on XRPL", t.loc["XRPL: XRP payment", "p50"], 0.05 * 0.964, 1.0),
        ("USDC on Solana", t.loc["Solana: USDC transfer", "p50"], 1.0323 * gbp_per_usd, 3.0),
        ("USDT on Tron", t.loc["Tron: USDT transfer, energy burned", "p50"], 1.0 * gbp_per_usd, 3.0 + t.loc["Tron: USDT transfer, energy burned", "p50"]),
    ]
    fig, ax = plt.subplots(figsize=(11, 4.8))
    fig.subplots_adjust(left=0.16, right=0.97, top=0.76, bottom=0.15)
    w = 0.25
    for i, (_lab, proto, kraken, revolut) in enumerate(rows):
        for j, (val, col, name) in enumerate(((proto, BLUE, "network (protocol) fee"), (kraken, ORANGE, "Kraken withdrawal fee"),
                                              (revolut, AQUA, "Revolut withdrawal fee"))):
            y = i + (j - 1) * w
            ax.barh(y, val, height=w * 0.9, color=col, edgecolor=SURFACE, label=name if i == 0 else None)
            ax.text(val * 1.15, y, f"£{val:.5f}" if val < 0.01 else f"£{val:.2f}", va="center", fontsize=8.5, color=INK2)
    ax.set_xscale("log")
    ax.set_xlim(1e-5, 30)
    _plain_log(ax)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows], color=INK2)
    ax.set_xlabel("pounds per transfer (log scale)")
    ax.grid(axis="y", visible=False)
    ax.legend(ncol=3, loc="upper left", bbox_to_anchor=(0, 1.12))
    return _finish(fig, "The network is nearly free; leaving the exchange is not",
                   "Median network fee actually paid (Oct 2024-Sep 2026) against published withdrawal fees. "
                   "Tron's fee is the median when energy is burned rather than staked.",
                   f"{SOURCE}. Stratified random blocks from public XRPL, Solana and Tron nodes; Kraken and Revolut fee pages "
                   "read 26 Oct 2026.", out / "fig7_fees.png")


# ------------------------------------------------------------------ 8. breakeven


def fig_breakeven(res: dict[str, Any], out: Path) -> Path:
    sides = res["sides"]
    rb = res["rpw_bench"].set_index("corridor")
    fig, (a, b) = plt.subplots(1, 2, figsize=(13, 5.8), gridspec_kw={"width_ratios": [1.15, 1]})
    fig.subplots_adjust(left=0.07, right=0.97, top=0.80, bottom=0.13, wspace=0.3)
    pct = np.linspace(0, 3, 121)
    fixed = np.linspace(0, 6, 121)
    P, F = np.meshgrid(pct, fixed)
    Z = 100 * (1 - (1 - P / 100) * (1 - F / SEND_GBP))
    cmap = LinearSegmentedColormap.from_list("seq", ["#cde2fb", "#86b6ef", "#2a78d6", "#184f95", "#0d366b"])
    im = a.contourf(P, F, Z, levels=np.arange(0, 6.01, 0.25), cmap=cmap)
    gbp = rb.loc[["GBR-IND", "GBR-NGA", "GBR-PHL", "GBR-KEN"]]
    for lvl, ls, lab in ((gbp.B1.median(), ":", "cheapest provider (B1, median of corridors)"),
                         (gbp.B2.median(), "--", "median digital provider (B2)")):
        cs = a.contour(P, F, Z, levels=[lvl], colors=[INK], linestyles=[ls], linewidths=1.5)
        a.clabel(cs, fmt={lvl: f"{lvl:.2f}%"}, fontsize=8)
        a.plot([], [], color=INK, linestyle=ls, label=lab)
    for s in sides.itertuples():
        col = RAIL[s.rail]
        pct_costs = s.on_pct + s.off_pct - 100 * s.fixed_send / SEND_GBP  # on/off include the fixed fees
        a.plot(pct_costs, s.fixed_send, "o", color=col, markersize=8, markeredgecolor=SURFACE, markeredgewidth=2)
    a.set_xlabel("percentage costs: trading fees + spreads, both ends (%)")
    a.set_ylabel("fixed costs: withdrawal + payout fees (£)")
    a.set_title("All-in cost of £200 (%), with observed Kraken routes")
    a.legend(loc="upper right", fontsize=8)
    fig.colorbar(im, ax=a, fraction=0.04, pad=0.02, label="cost %")
    curve = res["amount_curve"]
    cur = curve[curve.corridor == "GBR-PHL"]
    cols = {"XRP (XRPL)": ORANGE, "USDT (Tron)": AQUA, "USDC (Solana)": YELLOW,
            "Bank/MTO: median digital (RPW)": BLUE, "Bank/MTO: cheapest quote (Wise, Oct 2026)": VIOLET}
    for name, g in cur.groupby("series"):
        g = g.sort_values("amount")
        if "RPW" in name:  # RPW is only observed at £120 and £300; never extrapolate
            g = g[g.amount.between(120, 300)]
        b.plot(g.amount, g.cost_p50, "-o", color=cols.get(name, MUTED), markersize=6, markeredgecolor=SURFACE,
               markeredgewidth=1.5, label=name)
    b.set_xscale("log")
    b.set_xticks([50, 100, 200, 500, 1000], ["£50", "£100", "£200", "£500", "£1,000"])
    b.set_ylabel("cost, % (crypto excludes local premium)")
    b.set_title("UK → Philippines: cost by amount")
    b.legend(fontsize=8)
    return _finish(fig, "Flat withdrawal fees decide when the newer rails pay off",
                   "Left: closed-form cost of a £200 transfer; contours mark today's bank/MTO benchmarks. "
                   "Right: fixed fees make small crypto transfers expensive; RPW is interpolated only between £120 and £300.",
                   f"{SOURCE}. Fees and spreads as in chart 2; Wise comparison quotes collected Oct 2026.",
                   out / "fig8_breakeven.png")


def make_all(res: dict[str, Any], out: Path = FIGURES) -> list[Path]:
    style()
    return [f(res, out) for f in (fig_where, fig_costs, fig_premium, fig_speed, fig_var, fig_peg, fig_fees, fig_breakeven)]

