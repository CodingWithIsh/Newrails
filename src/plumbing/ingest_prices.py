"""Prices: XRP minute candles, stablecoin pegs, official FX, and local USDT markets.

Sources, all free and keyless (DATA_SOURCES.md has the full list):
- Binance public data: monthly 1-minute XRPUSDT files, each checked against its published SHA-256.
- Binance REST: daily TRX, SOL and XRP candles (to price network fees in pounds).
- Bitstamp: USDC/USD and USDT/USD, fiat-quoted, so a move away from $1 is unambiguous.
- Frankfurter (ECB reference rates) for INR, PHP, MXN and GBP; fawazahmed0 currency-api for NGN,
  KES and PKR, which the ECB does not publish (daily from 2 March 2024).
- RPW's own interbank rates, as quarterly anchors for NGN, KES and PKR before 2024.
- Local exchanges' daily USDT candles: WazirX and CoinDCX (INR), Quidax (NGN), Coins.ph (PHP),
  Bitso (MXN). Luno's candles need a key, so Kenya is covered by snapshots only.
"""

from __future__ import annotations

import hashlib
import io
import logging
import zipfile
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from plumbing import schemas
from plumbing.config import CACHE, PEG_EPISODE_THRESHOLD, PRICE_WINDOW, RAW
from plumbing.net import Client, envelope, load_json, save_json

log = logging.getLogger(__name__)

KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
              "trades", "taker_base", "taker_quote", "ignore"]


def months(start: date, end: date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def to_utc(values: Iterable[float] | pd.Series, unit: str | None = None) -> pd.DatetimeIndex:
    """Epoch numbers to UTC timestamps, inferring s / ms / µs from magnitude when `unit` is None.

    Binance switched its spot files from milliseconds to microseconds in January 2025.
    """
    arr = np.asarray(list(values) if not isinstance(values, pd.Series) else values, dtype="int64")
    if unit is None:
        top = int(np.max(np.abs(arr))) if len(arr) else 0
        unit = "us" if top > 10**14 else "ms" if top > 10**11 else "s"
    return pd.DatetimeIndex(pd.to_datetime(arr, unit=unit, utc=True))


def candles_frame(ts: Iterable[Any], o, h, low, c, v, unit: str | None = None) -> pd.DataFrame:
    df = pd.DataFrame({
        "ts": to_utc(ts, unit),
        "open": pd.to_numeric(pd.Series(o), errors="coerce").astype(float).to_numpy(),
        "high": pd.to_numeric(pd.Series(h), errors="coerce").astype(float).to_numpy(),
        "low": pd.to_numeric(pd.Series(low), errors="coerce").astype(float).to_numpy(),
        "close": pd.to_numeric(pd.Series(c), errors="coerce").astype(float).to_numpy(),
        "volume": pd.to_numeric(pd.Series(v), errors="coerce").astype(float).to_numpy(),
    })
    return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


# ------------------------------------------------------------------ Binance


BINANCE_VISION = "https://data.binance.vision/data/spot/monthly/klines/{sym}/{iv}/{sym}-{iv}-{month}.zip"
BINANCE_API = "https://api.binance.com/api/v3/klines"


def parse_binance_csv(raw: bytes) -> pd.DataFrame:
    """Read a Binance kline CSV (no header; some later files carry one)."""
    df = pd.read_csv(io.BytesIO(raw), header=None, names=KLINE_COLS)
    df = df[pd.to_numeric(df["open_time"], errors="coerce").notna()]
    return candles_frame(df["open_time"].astype("int64"), df["open"], df["high"], df["low"], df["close"], df["volume"])


def verify_checksum(blob: bytes, checksum_text: str) -> bool:
    expected = checksum_text.strip().split()[0].lower()
    return hashlib.sha256(blob).hexdigest() == expected


def fetch_binance_month(client: Client, symbol: str, interval: str, month: str, raw: Path = RAW) -> Path:
    """Download one monthly file (and its checksum) unless it is already cached and valid."""
    url = BINANCE_VISION.format(sym=symbol, iv=interval, month=month)
    path = raw / "binance" / symbol / interval / Path(url).name
    sums = path.with_suffix(".zip.CHECKSUM")
    if path.exists() and sums.exists() and verify_checksum(path.read_bytes(), sums.read_text()):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = client.get(url).content
    text = client.get(url + ".CHECKSUM").text
    if not verify_checksum(blob, text):
        raise ValueError(f"checksum mismatch for {url}")
    path.write_bytes(blob)
    sums.write_text(text)
    return path


def read_binance_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        return parse_binance_csv(zf.read(zf.namelist()[0]))


def binance_minutes(client: Client | None, symbol: str = "XRPUSDT", window=PRICE_WINDOW, raw: Path = RAW) -> pd.DataFrame:  # pragma: no cover - network orchestration, exercised by `make refresh`
    frames = []
    for month in months(*window):
        path = raw / "binance" / symbol / "1m" / f"{symbol}-1m-{month}.zip"
        if client is not None:
            path = fetch_binance_month(client, symbol, "1m", month, raw)
        frames.append(read_binance_zip(path))
    df = pd.concat(frames, ignore_index=True)
    lo, hi = pd.Timestamp(window[0], tz="UTC"), pd.Timestamp(window[1], tz="UTC") + pd.Timedelta(days=1)
    return df[(df.ts >= lo) & (df.ts < hi)].reset_index(drop=True)


def parse_binance_api(rows: list[list[Any]]) -> pd.DataFrame:
    if not rows:
        return candles_frame([], [], [], [], [], [])
    a = list(zip(*rows, strict=False))
    return candles_frame(a[0], a[1], a[2], a[3], a[4], a[5])


def fetch_binance_daily(client: Client, symbol: str, start: date, end: date, raw: Path = RAW) -> pd.DataFrame:  # pragma: no cover - network orchestration, exercised by `make refresh`
    rows: list[list[Any]] = []
    cursor = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp() * 1000)
    stop = int(datetime(end.year, end.month, end.day, tzinfo=UTC).timestamp() * 1000)
    while cursor <= stop:
        params = {"symbol": symbol, "interval": "1d", "startTime": cursor, "endTime": stop, "limit": 1000}
        batch = client.get_json(BINANCE_API, params)
        if not batch:
            break
        rows += batch
        cursor = int(batch[-1][0]) + 86_400_000
    save_json(raw / "binance" / "daily" / f"{symbol}_{start}_{end}.json.gz", envelope("binance", BINANCE_API, rows, {"symbol": symbol}))
    return parse_binance_api(rows)


# ------------------------------------------------------------------ Bitstamp


BITSTAMP_OHLC = "https://www.bitstamp.net/api/v2/ohlc/{pair}/"


def parse_bitstamp(payload: dict[str, Any]) -> pd.DataFrame:
    rows = payload["data"]["ohlc"]
    return candles_frame([int(r["timestamp"]) for r in rows], [r["open"] for r in rows], [r["high"] for r in rows],
                         [r["low"] for r in rows], [r["close"] for r in rows], [r["volume"] for r in rows], unit="s")


def fetch_bitstamp(client: Client, pair: str, step: int, start: datetime, end: datetime, raw: Path = RAW) -> pd.DataFrame:
    """Page through Bitstamp OHLC 1,000 candles at a time; each page is cached as its own raw file."""
    frames = []
    cursor = int(start.timestamp())
    stop = int(end.timestamp())
    while cursor < stop:
        path = raw / "bitstamp" / pair / str(step) / f"{cursor}.json.gz"
        if path.exists():
            payload = load_json(path)["payload"]
        else:
            params = {"step": step, "limit": 1000, "start": cursor}
            payload = client.get_json(BITSTAMP_OHLC.format(pair=pair), params)
            save_json(path, envelope("bitstamp", BITSTAMP_OHLC.format(pair=pair), payload, params))
        df = parse_bitstamp(payload)
        if df.empty:  # before the market was listed: jump a page forward rather than stop
            cursor += 1000 * step
            continue
        frames.append(df)
        cursor = int(df.ts.iloc[-1].timestamp()) + step
    out = pd.concat(frames, ignore_index=True).drop_duplicates("ts") if frames else parse_bitstamp({"data": {"ohlc": []}})
    return out[(out.ts >= pd.Timestamp(start)) & (out.ts < pd.Timestamp(end))].reset_index(drop=True)


BAD_PRINT_BAND = (0.5, 1.5)  # a stablecoin trade outside $0.50-$1.50 is a data error, not a depeg


def drop_bad_prints(candles: pd.DataFrame, band: tuple[float, float] = BAD_PRINT_BAND) -> tuple[pd.DataFrame, int]:
    """Remove candles with any price outside `band`; returns the clean frame and how many were removed.

    Bitstamp's hourly highs and lows include stray trades (e.g. one USDT print at $2,959 in November
    2022), so episode detection uses closes and these candles are excluded and counted.
    """
    lo, hi = band
    ok = candles[["open", "high", "low", "close"]].apply(lambda c: c.between(lo, hi)).all(axis=1)
    return candles[ok].reset_index(drop=True), int((~ok).sum())


def peg_episodes(hourly: pd.DataFrame, threshold: float = PEG_EPISODE_THRESHOLD, merge_gap_h: int = 24) -> pd.DataFrame:
    """Stress episodes found by rule, not by eye: hours whose close is more than `threshold` from $1,
    merged when less than `merge_gap_h` hours apart."""
    dev = (hourly["close"] - 1).abs()
    hits = hourly.loc[dev > threshold, "ts"].sort_values()
    episodes: list[dict[str, Any]] = []
    for ts in hits:
        if episodes and ts - episodes[-1]["end"] <= pd.Timedelta(hours=merge_gap_h):
            episodes[-1]["end"] = ts
            episodes[-1]["hours"] += 1
        else:
            episodes.append({"start": ts, "end": ts, "hours": 1})
    out = pd.DataFrame(episodes, columns=["start", "end", "hours"])
    signed = hourly["close"] - 1
    out["max_dev"] = [float(dev[(hourly.ts >= s) & (hourly.ts <= e)].max()) for s, e in zip(out.start, out.end, strict=True)]
    out["worst_price"] = [float(1 + signed[(hourly.ts >= s) & (hourly.ts <= e)].loc[lambda x: x.abs().idxmax()])
                          if len(out) else np.nan for s, e in zip(out.start, out.end, strict=True)]
    return out


def build_pegs(client: Client, cache: Path = CACHE, raw: Path = RAW, window=PRICE_WINDOW) -> dict[str, Path]:
    start, end = window
    t0 = datetime(start.year, start.month, start.day, tzinfo=UTC)
    t1 = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
    hourly, minutes, episodes, dropped = [], [], [], []
    for pair in ("usdcusd", "usdtusd"):
        h, n_bad = drop_bad_prints(fetch_bitstamp(client, pair, 3600, t0, t1, raw))
        schemas.CANDLES.validate(h)
        hourly.append(h.assign(pair=pair))
        ep = peg_episodes(h).assign(pair=pair)
        episodes.append(ep)
        for s, e in zip(ep.start, ep.end, strict=True):
            m = fetch_bitstamp(client, pair, 60, (s - pd.Timedelta(hours=24)).to_pydatetime(),
                               (e + pd.Timedelta(hours=72)).to_pydatetime(), raw)
            m, n_bad_m = drop_bad_prints(m)
            minutes.append(m.assign(pair=pair, episode_start=s))
            dropped.append({"pair": pair, "resolution": "1m", "episode_start": s, "dropped": n_bad_m})
        dropped.append({"pair": pair, "resolution": "1h", "episode_start": pd.NaT, "dropped": n_bad})
    out = {}
    for name, frames in (("peg_1h", hourly), ("peg_1m_episodes", minutes), ("peg_episodes", episodes),
                         ("peg_bad_prints", [pd.DataFrame(dropped)])):
        out[name] = cache / f"{name}.parquet"
        pd.concat(frames, ignore_index=True).to_parquet(out[name], index=False, compression="zstd")
    return out


# ------------------------------------------------------------------ official FX


FRANKFURTER = "https://api.frankfurter.dev/v1/{start}..{end}"
FAWAZ = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{day}/v1/currencies/{base}.min.json"
FAWAZ_FIRST_DAY = date(2024, 3, 2)


def parse_frankfurter(payload: dict[str, Any]) -> pd.DataFrame:
    rows = [{"date": pd.Timestamp(d), "base": payload["base"], "quote": q, "rate": float(v), "source": "ecb"}
            for d, rates in payload["rates"].items() for q, v in rates.items()]
    return pd.DataFrame(rows)


def fetch_frankfurter(client: Client, base: str, symbols: Iterable[str], start: date, end: date, raw: Path = RAW) -> pd.DataFrame:  # pragma: no cover - network orchestration, exercised by `make refresh`
    url = FRANKFURTER.format(start=start, end=end)
    params = {"base": base, "symbols": ",".join(symbols)}
    payload = client.get_json(url, params)
    save_json(raw / "fx" / f"frankfurter_{base}_{start}_{end}.json.gz", envelope("frankfurter", url, payload, params))
    return parse_frankfurter(payload)


def parse_fawaz(payload: dict[str, Any], base: str, quotes: Iterable[str]) -> list[dict[str, Any]]:
    rates = payload[base.lower()]
    return [{"date": pd.Timestamp(payload["date"]), "base": base.upper(), "quote": q.upper(),
             "rate": float(rates[q.lower()]), "source": "fawazahmed0"} for q in quotes if q.lower() in rates]


def fetch_fawaz(client: Client, base: str, quotes: Iterable[str], start: date, end: date, raw: Path = RAW) -> pd.DataFrame:  # pragma: no cover - network orchestration, exercised by `make refresh`
    rows: list[dict[str, Any]] = []
    quotes = list(quotes)
    day = max(start, FAWAZ_FIRST_DAY)
    while day <= end:
        path = raw / "fx" / "fawaz" / base.lower() / f"{day}.json.gz"
        if path.exists():
            payload = load_json(path)["payload"]
        else:
            url = FAWAZ.format(day=day, base=base.lower())
            try:
                payload = client.get_json(url)
            except Exception as exc:  # noqa: BLE001 - some days were never published; record and move on
                log.warning("fawaz %s %s missing: %s", base, day, exc)
                day += timedelta(days=1)
                continue
            payload = {"date": payload["date"], base.lower(): {q.lower(): payload[base.lower()].get(q.lower()) for q in quotes}}
            save_json(path, envelope("fawazahmed0", url, payload))
        rows += [r for r in parse_fawaz(payload, base, quotes) if np.isfinite(r["rate"])]
        day += timedelta(days=1)
    return pd.DataFrame(rows)


def rpw_fx_anchors(rpw_raw: pd.DataFrame, since: str = "2021_1Q") -> pd.DataFrame:
    """Official USD->local rates on RPW survey dates, from the US-sender corridors' interbank rates."""
    us = rpw_raw[(rpw_raw["source_code"] == "USA") & (rpw_raw["period"] >= since)]
    # Until early 2024 almost every RPW service to Nigeria paid out in US dollars (the Central Bank of
    # Nigeria's 2020 dollar-payout rule), so its "interbank rate" is 1.0. Every currency used here
    # trades above 10 per dollar, so rates below 10 mark a dollar payout and are excluded.
    us = us[us["interbank_fx"] > 10]
    g = us.groupby(["period", "destination_code"]).agg(date=("date", "median"), rate=("interbank_fx", "median"))
    out = g.reset_index().rename(columns={"destination_code": "dest"})
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    return out.dropna()


# ------------------------------------------------------------------ local USDT markets (daily)


LOCAL_MARKETS = {  # name: (url, quote currency, first day available)
    "wazirx:usdtinr": ("https://api.wazirx.com/sapi/v1/klines", "INR"),
    "coindcx:I-USDT_INR": ("https://public.coindcx.com/market_data/candles", "INR"),
    "quidax:usdtngn": ("https://app.quidax.io/api/v1/markets/usdtngn/k", "NGN"),
    "coinsph:USDTPHP": ("https://api.pro.coins.ph/openapi/quote/v1/klines", "PHP"),
    "bitso:usdt_mxn": ("https://api.bitso.com/v3/ohlc", "MXN"),
}


def parse_local(market: str, payload: Any) -> pd.DataFrame:
    if market.startswith("wazirx"):
        a = list(zip(*payload, strict=False)) or [()] * 6
        return candles_frame(a[0], a[1], a[2], a[3], a[4], a[5], unit="s")
    if market.startswith("coindcx"):
        return candles_frame([r["time"] for r in payload], [r["open"] for r in payload], [r["high"] for r in payload],
                             [r["low"] for r in payload], [r["close"] for r in payload], [r["volume"] for r in payload], unit="ms")
    if market.startswith("quidax"):
        d = payload["data"]
        a = list(zip(*d, strict=False)) or [()] * 6
        return candles_frame(a[0], a[1], a[2], a[3], a[4], a[5], unit="s")
    if market.startswith("coinsph"):
        a = list(zip(*payload, strict=False)) or [()] * 6
        return candles_frame(a[0], a[1], a[2], a[3], a[4], a[5], unit="ms")
    if market.startswith("bitso"):
        p = payload["payload"]
        return candles_frame([r["bucket_start_time"] for r in p], [r["first_rate"] for r in p], [r["max_rate"] for r in p],
                             [r["min_rate"] for r in p], [r["last_rate"] for r in p], [r["volume"] for r in p], unit="ms")
    raise KeyError(market)


def _local_request(market: str, start_ms: int, end_ms: int) -> tuple[str, dict[str, Any]]:
    url, _ = LOCAL_MARKETS[market]
    if market.startswith("wazirx"):
        return url, {"symbol": "usdtinr", "interval": "1d", "limit": 1000, "startTime": start_ms // 1000}
    if market.startswith("coindcx"):
        return url, {"pair": "I-USDT_INR", "interval": "1d", "limit": 1000, "startTime": start_ms, "endTime": end_ms}
    if market.startswith("quidax"):
        return url, {"period": 1440, "limit": 1000, "timestamp": start_ms // 1000}
    if market.startswith("coinsph"):
        return url, {"symbol": "USDTPHP", "interval": "1d", "limit": 1000, "startTime": start_ms}
    return url, {"book": "usdt_mxn", "time_bucket": 86400, "start": start_ms, "end": min(end_ms, start_ms + 360 * 86_400_000)}


def fetch_local(client: Client, market: str, start: date, end: date, raw: Path = RAW) -> pd.DataFrame:  # pragma: no cover - network orchestration, exercised by `make refresh`
    """Page forward through a venue's daily candles until no new days arrive."""
    frames = []
    cursor = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp() * 1000)
    stop = int(datetime(end.year, end.month, end.day, tzinfo=UTC).timestamp() * 1000) + 86_400_000
    while cursor < stop:
        url, params = _local_request(market, cursor, stop)
        payload = client.get_json(url, params)
        save_json(raw / "local" / market.replace(":", "_") / f"{cursor}.json.gz", envelope(market, url, payload, params))
        df = parse_local(market, payload)
        df = df[df.ts >= pd.Timestamp(cursor, unit="ms", tz="UTC")]
        if df.empty:
            if market.startswith("bitso") and cursor + 360 * 86_400_000 < stop:
                cursor += 360 * 86_400_000  # Bitso has no data before 2024: skip empty years
                continue
            break
        frames.append(df)
        cursor = int(df.ts.iloc[-1].timestamp() * 1000) + 86_400_000
    out = pd.concat(frames, ignore_index=True).drop_duplicates("ts") if frames else parse_local("coindcx:x", [])
    return out[out.ts < pd.Timestamp(stop, unit="ms", tz="UTC")].reset_index(drop=True)


def local_premium(local: pd.DataFrame, fx: pd.DataFrame, quote: str) -> pd.DataFrame:
    """Daily USDT close on a local venue against the official USD->local rate: premium = close / official - 1."""
    rates = fx[(fx["base"] == "USD") & (fx["quote"] == quote)].sort_values("date")
    left = local.assign(date=local["ts"].dt.tz_convert(None).dt.normalize()).sort_values("date")
    merged = pd.merge_asof(left, rates[["date", "rate", "source"]], on="date", direction="backward",
                           tolerance=pd.Timedelta(days=4))
    merged["premium"] = merged["close"] / merged["rate"] - 1
    return merged.dropna(subset=["rate"])


# ------------------------------------------------------------------ build


def compact_minutes(df: pd.DataFrame) -> pd.DataFrame:
    """Minute closes on a complete UTC grid (gaps left as NaN, never filled), close as float32."""
    grid = pd.date_range(df.ts.min().floor("min"), df.ts.max().floor("min"), freq="min", tz="UTC")
    out = df.set_index("ts")["close"].reindex(grid).astype("float32").rename("close").to_frame()
    out.index.name = "ts"
    return out.reset_index()


def build_cache(client: Client | None = None, cache: Path = CACHE, raw: Path = RAW,
                rpw_raw: pd.DataFrame | None = None) -> dict[str, Path]:  # pragma: no cover - network orchestration, exercised by `make refresh`
    """Pull (or re-read) every price series and write the compact versions the analysis uses."""
    client = client or Client()
    cache.mkdir(parents=True, exist_ok=True)
    start, end = PRICE_WINDOW
    out: dict[str, Path] = {}

    xrp = binance_minutes(client, "XRPUSDT", PRICE_WINDOW, raw)
    schemas.CANDLES.validate(xrp)
    out["xrp_1m"] = cache / "xrp_usdt_1m.parquet"
    compact_minutes(xrp).to_parquet(out["xrp_1m"], index=False, compression="zstd")

    daily = []
    for sym in ("XRPUSDT", "TRXUSDT", "SOLUSDT"):
        d = fetch_binance_daily(client, sym, start, end + timedelta(days=30), raw)
        daily.append(d.assign(symbol=sym))
    out["native_daily"] = cache / "native_daily.parquet"
    pd.concat(daily, ignore_index=True).to_parquet(out["native_daily"], index=False, compression="zstd")

    out.update(build_pegs(client, cache, raw))

    xrp_gbp = fetch_bitstamp(client, "xrpgbp", 60, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC), raw)
    out["xrp_gbp_1m_bitstamp"] = cache / "xrp_gbp_1m_bitstamp_2026_09.parquet"
    xrp_gbp.to_parquet(out["xrp_gbp_1m_bitstamp"], index=False, compression="zstd")

    fx_end = date.today()
    fx = [fetch_frankfurter(client, "USD", ["INR", "PHP", "MXN", "GBP"], start - timedelta(days=7), fx_end, raw),
          fetch_fawaz(client, "usd", ["ngn", "kes", "pkr", "inr", "php", "mxn", "gbp"], start, fx_end, raw)]
    fx_all = pd.concat(fx, ignore_index=True)
    if rpw_raw is not None:
        anchors = rpw_fx_anchors(rpw_raw)
        codes = {"NGA": "NGN", "KEN": "KES", "PAK": "PKR", "IND": "INR", "PHL": "PHP", "MEX": "MXN"}
        anchors = anchors[anchors.dest.isin(codes)].assign(base="USD", quote=lambda d: d.dest.map(codes), source="rpw_interbank")
        fx_all = pd.concat([fx_all, anchors[["date", "base", "quote", "rate", "source"]]], ignore_index=True)
    fx_all = fx_all.drop_duplicates(["date", "base", "quote", "source"])
    schemas.FX_DAILY.validate(fx_all)
    out["fx_daily"] = cache / "fx_daily.parquet"
    fx_all.to_parquet(out["fx_daily"], index=False, compression="zstd")

    local = []
    for market, (_, quote) in LOCAL_MARKETS.items():
        try:
            df = fetch_local(client, market, start, fx_end, raw)
        except Exception as exc:  # noqa: BLE001 - one venue failing should not stop the build
            log.warning("local market %s failed: %s", market, exc)
            continue
        local.append(df.assign(market=market, quote=quote))
    out["local_usdt_daily"] = cache / "local_usdt_daily.parquet"
    pd.concat(local, ignore_index=True).to_parquet(out["local_usdt_daily"], index=False, compression="zstd")
    return out
