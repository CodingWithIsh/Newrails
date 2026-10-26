"""On- and off-ramp prices: public order books, Wise comparison quotes, and the snapshot collector.

The collector polls order books every 10 minutes and Wise quotes on the same clock, writing raw
responses to data/raw/snapshots/ as JSON lines (one envelope per request). Nothing is parsed at
collection time, so a parser bug can be fixed later without losing data.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from plumbing import schemas
from plumbing.config import CACHE, MANUAL, RAW
from plumbing.net import Client, append_jsonl, envelope, iter_jsonl, utcnow

log = logging.getLogger(__name__)

SNAPSHOTS = RAW / "snapshots"
MAX_LEVELS = 100

Levels = list[tuple[float, float]]


@dataclass(frozen=True)
class BookSpec:
    venue: str
    symbol: str  # the venue's own market id
    base: str
    quote: str
    role: str  # "onramp_gbp", "onramp_usd", "offramp" or "swap"

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.symbol}"


BOOKS: tuple[BookSpec, ...] = (
    # UK on-ramps (GBP)
    BookSpec("kraken", "XRPGBP", "XRP", "GBP", "onramp_gbp"),
    BookSpec("kraken", "USDCGBP", "USDC", "GBP", "onramp_gbp"),
    BookSpec("kraken", "USDTGBP", "USDT", "GBP", "onramp_gbp"),
    BookSpec("coinbase", "USDC-GBP", "USDC", "GBP", "onramp_gbp"),
    BookSpec("coinbase", "USDT-GBP", "USDT", "GBP", "onramp_gbp"),
    BookSpec("bitstamp", "xrpgbp", "XRP", "GBP", "onramp_gbp"),
    BookSpec("bitstamp", "gbpusd", "GBP", "USD", "onramp_gbp"),
    # US on-ramps (USD), for the $200 control
    BookSpec("kraken", "XRPUSD", "XRP", "USD", "onramp_usd"),
    BookSpec("kraken", "USDTUSD", "USDT", "USD", "onramp_usd"),
    BookSpec("kraken", "USDCUSD", "USDC", "USD", "onramp_usd"),
    BookSpec("coinbase", "XRP-USD", "XRP", "USD", "onramp_usd"),
    BookSpec("coinbase", "USDT-USD", "USDT", "USD", "onramp_usd"),
    BookSpec("bitstamp", "xrpusd", "XRP", "USD", "onramp_usd"),
    BookSpec("bitstamp", "usdcusd", "USDC", "USD", "onramp_usd"),
    BookSpec("bitstamp", "usdtusd", "USDT", "USD", "onramp_usd"),
    # Off-ramps
    BookSpec("coindcx", "I-USDT_INR", "USDT", "INR", "offramp"),
    BookSpec("coindcx", "I-USDC_INR", "USDC", "INR", "offramp"),
    BookSpec("coindcx", "I-XRP_INR", "XRP", "INR", "offramp"),
    BookSpec("wazirx", "usdtinr", "USDT", "INR", "offramp"),
    BookSpec("wazirx", "xrpinr", "XRP", "INR", "offramp"),
    BookSpec("luno", "USDTNGN", "USDT", "NGN", "offramp"),
    BookSpec("luno", "USDCNGN", "USDC", "NGN", "offramp"),
    BookSpec("luno", "XRPNGN", "XRP", "NGN", "offramp"),
    BookSpec("luno", "USDTKES", "USDT", "KES", "offramp"),
    BookSpec("quidax", "usdtngn", "USDT", "NGN", "offramp"),
    BookSpec("coinsph", "USDTPHP", "USDT", "PHP", "offramp"),
    BookSpec("coinsph", "USDCPHP", "USDC", "PHP", "offramp"),
    BookSpec("coinsph", "XRPPHP", "XRP", "PHP", "offramp"),
    BookSpec("bitso", "usdt_mxn", "USDT", "MXN", "offramp"),
    BookSpec("bitso", "xrp_mxn", "XRP", "MXN", "offramp"),
    BookSpec("bitso", "rlusd_mxn", "RLUSD", "MXN", "offramp"),
    # Swaps at the destination, for routes whose coin has no local market
    BookSpec("luno", "USDCUSDT", "USDC", "USDT", "swap"),
    BookSpec("luno", "XRPUSDT", "XRP", "USDT", "swap"),
)

BOOK_URLS: dict[str, Callable[[str], tuple[str, dict[str, Any]]]] = {
    "kraken": lambda s: ("https://api.kraken.com/0/public/Depth", {"pair": s, "count": MAX_LEVELS}),
    "coinbase": lambda s: (f"https://api.exchange.coinbase.com/products/{s}/book", {"level": 2}),
    "bitstamp": lambda s: (f"https://www.bitstamp.net/api/v2/order_book/{s}/", {}),
    "coindcx": lambda s: ("https://public.coindcx.com/market_data/orderbook", {"pair": s}),
    "wazirx": lambda s: ("https://api.wazirx.com/sapi/v1/depth", {"symbol": s, "limit": MAX_LEVELS}),
    "luno": lambda s: ("https://api.luno.com/api/1/orderbook_top", {"pair": s}),
    "quidax": lambda s: (f"https://app.quidax.io/api/v1/markets/{s}/depth", {}),
    "coinsph": lambda s: ("https://api.pro.coins.ph/openapi/quote/v1/depth", {"symbol": s, "limit": MAX_LEVELS}),
    "bitso": lambda s: ("https://api.bitso.com/v3/order_book/", {"book": s, "aggregate": "true"}),
}


# ---------------------------------------------------------------- parsing (pure)


def _pairs(rows: Iterable[Any]) -> Levels:
    out = []
    for r in rows:
        if isinstance(r, dict):
            price, qty = r["price"], (r["volume"] if "volume" in r else r["amount"])
        else:
            price, qty = r[0], r[1]
        out.append((float(price), float(qty)))
    return out


def _from_dict(d: dict[str, Any]) -> Levels:
    return [(float(p), float(q)) for p, q in d.items()]


def normalise(bids: Levels, asks: Levels, max_levels: int = MAX_LEVELS) -> tuple[Levels, Levels]:
    """Sort bids high to low and asks low to high, drop empty levels, keep the top `max_levels`."""
    bids = sorted(((p, q) for p, q in bids if p > 0 and q > 0), key=lambda x: -x[0])[:max_levels]
    asks = sorted(((p, q) for p, q in asks if p > 0 and q > 0), key=lambda x: x[0])[:max_levels]
    return bids, asks


def parse_book(venue: str, payload: Any) -> tuple[Levels, Levels]:
    """Turn one venue's order-book response into (bids, asks) of (price, quantity in base units)."""
    if venue == "kraken":
        if payload.get("error"):
            raise ValueError(f"kraken error: {payload['error']}")
        book = next(iter(payload["result"].values()))
        bids, asks = _pairs(book["bids"]), _pairs(book["asks"])
    elif venue == "coindcx":
        bids, asks = _from_dict(payload["bids"]), _from_dict(payload["asks"])
    elif venue == "quidax":
        bids, asks = _pairs(payload["data"]["bids"]), _pairs(payload["data"]["asks"])
    elif venue == "bitso":
        bids, asks = _pairs(payload["payload"]["bids"]), _pairs(payload["payload"]["asks"])
    elif venue in {"coinbase", "bitstamp", "wazirx", "luno", "coinsph"}:
        if "bids" not in payload:
            raise ValueError(f"{venue}: no book in response: {str(payload)[:200]}")
        bids, asks = _pairs(payload["bids"]), _pairs(payload["asks"])
    else:
        raise KeyError(f"unknown venue {venue!r}")
    return normalise(bids, asks)


def utc(ts: datetime | str) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_convert("UTC") if t.tzinfo else t.tz_localize("UTC")


def book_row(spec: BookSpec, ts: datetime | str, payload: Any) -> dict[str, Any]:
    bids, asks = parse_book(spec.venue, payload)
    best_bid = bids[0][0] if bids else float("nan")
    best_ask = asks[0][0] if asks else float("nan")
    mid = (best_bid + best_ask) / 2
    return {
        "ts": utc(ts),
        "venue": spec.venue,
        "symbol": spec.symbol,
        "base": spec.base,
        "quote": spec.quote,
        "role": spec.role,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread_bps": (best_ask - best_bid) / mid * 1e4,
        "crossed": bool(best_bid >= best_ask),
        "bid_px": [p for p, _ in bids],
        "bid_qty": [q for _, q in bids],
        "ask_px": [p for p, _ in asks],
        "ask_qty": [q for _, q in asks],
    }


# ---------------------------------------------------------------- Wise comparison quotes

WISE_URL = "https://api.wise.com/v4/comparisons/"
WISE_PAIRS: tuple[tuple[str, str], ...] = (
    ("GBP", "INR"), ("GBP", "NGN"), ("GBP", "PHP"), ("GBP", "PKR"), ("GBP", "KES"), ("GBP", "USD"),
    ("USD", "INR"), ("USD", "NGN"), ("USD", "PHP"), ("USD", "PKR"), ("USD", "KES"), ("USD", "MXN"),
)
WISE_EXTRA_AMOUNTS = (50, 120, 300, 500, 1000)


def parse_wise(payload: dict[str, Any], pulled_at: datetime | str) -> list[dict[str, Any]]:
    """One row per provider quote. `markup` is Wise's own estimate of the margin over mid-market (%)."""
    rows = []
    for p in payload.get("providers", []):
        for q in p.get("quotes", []):
            delivery = (q.get("deliveryEstimation") or {}).get("duration") or {}
            rows.append({
                "pulled_at": utc(pulled_at),
                "send_ccy": payload["sourceCurrency"],
                "recv_ccy": payload["targetCurrency"],
                "send_amount": float(payload["amount"]),
                "provider": p["name"],
                "provider_alias": p.get("alias"),
                "provider_type": p.get("type"),
                "fee": float(q["fee"]) if q.get("fee") is not None else float("nan"),
                "rate": float(q["rate"]),
                "received": float(q["receivedAmount"]) if q.get("receivedAmount") is not None else float("nan"),
                "markup_pct": float(q["markup"]) if q.get("markup") is not None else float("nan"),
                "is_mid": bool(q.get("isConsideredMidMarketRate", False)),
                "collected_at": pd.Timestamp(q["dateCollected"]) if q.get("dateCollected") else pd.NaT,
                "delivery_min": delivery.get("min"),
                "delivery_max": delivery.get("max"),
            })
    return rows


# ---------------------------------------------------------------- collection (network)


def snapshot_books(client: Client, books: Iterable[BookSpec] = BOOKS, out: Path = SNAPSHOTS) -> int:
    """Fetch every book once. Failures are recorded as envelopes with an `error`, never skipped silently."""
    ok = 0
    for spec in books:
        url, params = BOOK_URLS[spec.venue](spec.symbol)
        rec = envelope(f"book:{spec.key}", url, None, params)
        try:
            rec["payload"] = client.get_json(url, params)
            parse_book(spec.venue, rec["payload"])  # validate now so errors are logged with the pull
            ok += 1
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, then the round continues
            rec["error"] = f"{type(exc).__name__}: {exc}"[:500]
            log.warning("book %s failed: %s", spec.key, rec["error"])
        append_jsonl(out / "books" / f"{rec['pulled_at'][:10]}.jsonl", rec)
    return ok


def snapshot_wise(client: Client, amounts: Iterable[float] = (200,), out: Path = SNAPSHOTS) -> int:
    ok = 0
    for amount in amounts:
        for src, dst in WISE_PAIRS:
            params = {"sourceCurrency": src, "targetCurrency": dst, "sendAmount": amount}
            rec = envelope("wise", WISE_URL, None, params)
            try:
                rec["payload"] = client.get_json(WISE_URL, params)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                rec["error"] = f"{type(exc).__name__}: {exc}"[:500]
                log.warning("wise %s->%s %s failed: %s", src, dst, amount, rec["error"])
            append_jsonl(out / "wise" / f"{rec['pulled_at'][:10]}.jsonl", rec)
    return ok


def collect(hours: float = 72.0, every_min: float = 10.0, extra_every_h: float = 6.0,
            client: Client | None = None, out: Path = SNAPSHOTS) -> None:
    """Poll books and Wise quotes on a fixed clock until `hours` have passed."""
    client = client or Client()
    start = time.monotonic()
    last_extra = -1e9
    n = 0
    while time.monotonic() - start < hours * 3600:
        tick = time.monotonic()
        nb = snapshot_books(client, out=out)
        amounts: list[float] = [200]
        if tick - last_extra >= extra_every_h * 3600:
            amounts += list(WISE_EXTRA_AMOUNTS)
            last_extra = tick
        nw = snapshot_wise(client, amounts, out=out)
        n += 1
        log.info("round %d at %s: %d/%d books, %d wise quotes", n, utcnow().isoformat(timespec="seconds"),
                 nb, len(BOOKS), nw)
        time.sleep(max(0.0, every_min * 60 - (time.monotonic() - tick)))


# ---------------------------------------------------------------- cache build


def _envelopes(folder: Path) -> Iterable[dict[str, Any]]:
    for path in sorted(folder.glob("*.jsonl")):
        yield from iter_jsonl(path)


def build_books(raw: Path = SNAPSHOTS, books: Iterable[BookSpec] = BOOKS) -> pd.DataFrame:
    specs = {f"book:{b.key}": b for b in books}
    rows = []
    for rec in _envelopes(raw / "books"):
        spec = specs.get(rec.get("source", ""))
        if spec is None or rec.get("error") or rec.get("payload") is None:
            continue
        try:
            rows.append(book_row(spec, rec["pulled_at"], rec["payload"]))
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            log.warning("unparseable %s at %s: %s", spec.key, rec["pulled_at"], exc)
    return pd.DataFrame(rows)


def build_wise(raw: Path = SNAPSHOTS) -> pd.DataFrame:
    rows = []
    for rec in _envelopes(raw / "wise"):
        if rec.get("error") or not rec.get("payload"):
            continue
        rows.extend(parse_wise(rec["payload"], rec["pulled_at"]))
    return pd.DataFrame(rows)


def collection_log(raw: Path = SNAPSHOTS) -> pd.DataFrame:
    """Every attempted request, with its outcome: used to report gaps honestly."""
    rows = []
    for kind in ("books", "wise"):
        for rec in _envelopes(raw / kind):
            rows.append({"kind": kind, "source": rec.get("source"), "pulled_at": rec.get("pulled_at"),
                         "params": str(rec.get("params")), "ok": not rec.get("error"),
                         "error": rec.get("error")})
    return pd.DataFrame(rows)


def build_cache(raw: Path = SNAPSHOTS, cache: Path = CACHE) -> dict[str, Path]:
    cache.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, frame in (("ramp_books", build_books(raw)), ("wise_quotes", build_wise(raw)),
                        ("collection_log", collection_log(raw))):
        path = cache / f"{name}.parquet"
        frame.to_parquet(path, index=False, compression="zstd")
        out[name] = path
    return out


# ---------------------------------------------------------------- hand-collected fees and availability


def load_fees(path: Path = MANUAL / "fees.yaml") -> list[schemas.FeeEntry]:
    with path.open() as fh:
        return [schemas.FeeEntry(**row) for row in yaml.safe_load(fh)]


def load_availability(path: Path = MANUAL / "availability.yaml") -> list[schemas.Availability]:
    with path.open() as fh:
        return [schemas.Availability(**row) for row in yaml.safe_load(fh)]


def fee_lookup(fees: Iterable[schemas.FeeEntry]) -> dict[tuple[str, str, str, str | None], schemas.FeeEntry]:
    """Index fees by (provider, leg, asset, network); duplicate keys are an error."""
    out: dict[tuple[str, str, str, str | None], schemas.FeeEntry] = {}
    for f in fees:
        key = (f.provider, f.leg, f.asset, f.network)
        if key in out:
            raise ValueError(f"duplicate fee entry {key}")
        out[key] = f
    return out
