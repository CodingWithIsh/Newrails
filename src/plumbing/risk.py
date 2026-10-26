"""Risk: XRP price drift during a transfer, stablecoin peg deviations, and network fee tails.

XRP value-at-risk uses historical simulation on overlapping h-minute log returns. Overlap makes
neighbouring returns dependent, so confidence intervals come from a moving-block bootstrap with
one-day blocks, and the Kupiec test uses non-overlapping windows only.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd
from scipy import stats

from plumbing.config import PEG_BANDS_BPS, PEG_EPISODE_THRESHOLD, SEED

# ------------------------------------------------------------------ returns and VaR


def horizon_returns(close: pd.Series | np.ndarray, h: int) -> np.ndarray:
    """Overlapping h-step log returns on a regular grid; pairs touching a gap (NaN) are dropped."""
    p = np.asarray(close, dtype=float)
    if h < 1 or h >= len(p):
        raise ValueError("horizon must be at least 1 and shorter than the series")
    r = np.log(p[h:]) - np.log(p[:-h])
    return r[np.isfinite(r)]


def var_es(returns: np.ndarray, level: float = 0.99) -> tuple[float, float]:
    """Value-at-risk and expected shortfall as positive loss fractions (0.01 = 1% of the amount)."""
    r = np.asarray(returns, dtype=float)
    if not len(r):
        raise ValueError("no returns")
    q = np.quantile(r, 1 - level)
    loss_var = 1 - np.exp(q)
    tail = r[r <= q]
    loss_es = float(np.mean(1 - np.exp(tail)))
    return float(loss_var), loss_es


def block_bootstrap_var(returns: np.ndarray, level: float = 0.99, block: int = 1440, reps: int = 200,
                        seed: int = SEED, ci: float = 0.90) -> tuple[float, float]:
    """Moving-block bootstrap confidence interval for VaR (blocks of `block` consecutive returns)."""
    r = np.asarray(returns, dtype=float)
    n = len(r)
    block = max(1, min(block, n))
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    k = int((1 - level) * n)
    draws = np.empty(reps)
    for i in range(reps):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        sample = (r[s:s + block] for s in starts)
        x = np.concatenate(list(sample))[:n]
        q = np.partition(x, k)[k]
        draws[i] = 1 - np.exp(q)
    lo, hi = np.quantile(draws, [(1 - ci) / 2, 1 - (1 - ci) / 2])
    return float(lo), float(hi)


def kupiec(exceedances: int, n: int, level: float) -> tuple[float, float]:
    """Kupiec proportion-of-failures test. Returns (likelihood-ratio statistic, p-value)."""
    if n <= 0 or not 0 <= exceedances <= n:
        raise ValueError("need 0 <= exceedances <= n and n > 0")
    p = 1 - level
    x = exceedances
    phat = x / n

    def ll(prob: float) -> float:
        a = (n - x) * np.log(1 - prob) if x < n else 0.0
        b = x * np.log(prob) if x > 0 else 0.0
        return a + b

    lr = -2 * (ll(p) - ll(phat)) if 0 < phat < 1 else -2 * ll(p)
    return float(lr), float(1 - stats.chi2.cdf(lr, df=1))


def backtest(close: pd.Series, h: int, level: float = 0.99, window_days: int = 30) -> dict[str, float]:
    """Forecast VaR from the previous `window_days` of h-minute returns, then check the next
    non-overlapping h-minute window; repeat. Counts how often the loss beat the forecast."""
    p = np.asarray(close, dtype=float)
    win = window_days * 1440
    exceed, n = 0, 0
    for t in range(win, len(p) - h, max(h, 60)):  # at most one test an hour keeps windows independent
        past = horizon_returns(p[t - win:t + 1], h)
        if len(past) < 1000 or not (np.isfinite(p[t]) and np.isfinite(p[t + h])):
            continue
        v, _ = var_es(past, level)
        loss = 1 - p[t + h] / p[t]
        exceed += int(loss > v)
        n += 1
    lr, pval = kupiec(exceed, n, level) if n else (np.nan, np.nan)
    return {"horizon_min": h, "level": level, "tests": n, "exceedances": exceed,
            "expected": n * (1 - level), "kupiec_lr": lr, "kupiec_p": pval}


def var_table(close: pd.Series, ts: pd.Series, horizons: Iterable[int], levels: Iterable[float],
              amount: float = 200.0, bootstrap_reps: int = 200) -> pd.DataFrame:
    rows = []
    for h in horizons:
        r = horizon_returns(close, h)
        for lvl in levels:
            v, es = var_es(r, lvl)
            lo, hi = block_bootstrap_var(r, lvl, reps=bootstrap_reps)
            rows.append({"horizon_min": h, "level": lvl, "n": len(r), "var_pct": 100 * v, "es_pct": 100 * es,
                         "var_lo_pct": 100 * lo, "var_hi_pct": 100 * hi, "var_gbp": amount * v,
                         "es_gbp": amount * es, "sqrt_time_ratio": np.nan})
    out = pd.DataFrame(rows)
    for lvl in levels:
        base = out[(out.horizon_min == min(horizons)) & (out.level == lvl)]["var_pct"].iloc[0]
        m = out.level == lvl
        out.loc[m, "sqrt_time_ratio"] = out.loc[m, "var_pct"] / (base * np.sqrt(out.loc[m, "horizon_min"] / min(horizons)))
    return out


def var_by_group(close: pd.Series, ts: pd.Series, h: int, level: float, by: str) -> pd.DataFrame:
    """VaR by calendar year, or by the volatility regime a sender could see beforehand
    (quintile of the trailing 24-hour realised volatility)."""
    p = np.asarray(close, dtype=float)
    t = pd.DatetimeIndex(ts)
    r = np.log(p[h:]) - np.log(p[:-h])
    start = t[:-h]
    if by == "year":
        key = pd.Series(start.year, index=range(len(start)))
    elif by == "vol_regime":
        r1 = pd.Series(np.log(p[1:]) - np.log(p[:-1]))
        trailing = r1.rolling(1440, min_periods=720).std().shift(1)  # known before the transfer starts
        trailing = pd.concat([pd.Series([np.nan]), trailing], ignore_index=True)[: len(start)]
        key = pd.qcut(trailing, 5, labels=["Q1 calm", "Q2", "Q3", "Q4", "Q5 stormy"])
    else:
        raise ValueError("by must be 'year' or 'vol_regime'")
    df = pd.DataFrame({"r": r, "g": key.to_numpy()}).dropna()
    rows = []
    for g, part in df.groupby("g", observed=True):
        v, es = var_es(part["r"].to_numpy(), level)
        rows.append({by: g, "n": len(part), "var_pct": 100 * v, "es_pct": 100 * es})
    return pd.DataFrame(rows)


def prob_drift_exceeds(returns: np.ndarray, saving_pct: float) -> float:
    """Share of historical windows in which the price fell by more than `saving_pct` percent."""
    r = np.asarray(returns, dtype=float)
    return float(np.mean((1 - np.exp(r)) * 100 > saving_pct))


# ------------------------------------------------------------------ stablecoin pegs


def peg_bands(hourly: pd.DataFrame, bands_bps: Iterable[int] = PEG_BANDS_BPS) -> pd.DataFrame:
    """Share of hourly closes more than each band away from $1, per pair and overall."""
    rows = []
    for pair, g in hourly.groupby("pair"):
        dev = (g["close"] - 1).abs() * 1e4
        row = {"pair": pair, "hours": len(g), "first": g["ts"].min(), "last": g["ts"].max(),
               "worst_close": float(g.loc[(g["close"] - 1).abs().idxmax(), "close"])}
        for b in bands_bps:
            row[f"share_beyond_{b}bp"] = float((dev > b).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def episode_recovery(minutes: pd.DataFrame, threshold: float = PEG_EPISODE_THRESHOLD) -> pd.DataFrame:
    """For each episode window of minute data: worst price, minutes beyond `threshold`, and the time
    from the first to the last minute beyond it."""
    rows = []
    for (pair, start), g in minutes.groupby(["pair", "episode_start"]):
        g = g.sort_values("ts")
        out = g[(g["close"] - 1).abs() > threshold]
        rows.append({
            "pair": pair, "episode_start": start,
            "worst_minute_close": float(g.loc[(g["close"] - 1).abs().idxmax(), "close"]),
            "minutes_beyond": len(out),
            "hours_first_to_last": (out["ts"].max() - out["ts"].min()).total_seconds() / 3600 if len(out) else 0.0,
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ network fees in pounds


def to_gbp(fees: pd.DataFrame, native_daily: pd.DataFrame, gbpusd_daily: pd.DataFrame,
           symbol: str, value_col: str = "fee_native") -> pd.Series:
    """Convert native-token fees to pounds at that day's close (token/USDT ~ USD, then USD -> GBP)."""
    px = native_daily[native_daily["symbol"] == symbol].assign(date=lambda d: d["ts"].dt.tz_convert(None).dt.normalize())
    fx = gbpusd_daily.sort_values("date")
    day = fees["time"].dt.tz_convert(None).dt.normalize()
    usd = day.map(px.set_index("date")["close"])
    gbpusd = pd.merge_asof(pd.DataFrame({"date": day}).reset_index().sort_values("date"), fx[["date", "rate"]],
                           on="date", direction="backward").set_index("index")["rate"]
    return fees[value_col] * usd / gbpusd.reindex(fees.index)


def fee_tails(values: pd.Series, by: pd.Series | None = None) -> pd.DataFrame:
    qs = [0.5, 0.9, 0.99, 0.999]
    if by is None:
        return pd.DataFrame([{**{f"p{int(q * 1000) / 10:g}": values.quantile(q) for q in qs},
                              "max": values.max(), "n": values.count()}])
    g = values.groupby(by)
    out = pd.concat({f"p{int(q * 1000) / 10:g}": g.quantile(q) for q in qs}, axis=1)
    out["max"] = g.max()
    out["n"] = g.count()
    return out
