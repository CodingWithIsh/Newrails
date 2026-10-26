"""XRP Ledger: ledger timing and fees from public servers.

Two measurements, because the ledger record cannot give both:
- Fees, from a stratified random sample of historical ledgers (transactions expanded).
- Ledger intervals. A ledger's `close_time` is rounded to `close_time_resolution` (10 s), so the
  gap between two consecutive ledgers cannot be read from history. Instead, history gives the mean
  interval over spans of many ledgers, and a live subscription to the ledger stream gives each
  ledger's arrival time to the millisecond.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from plumbing import schemas
from plumbing.config import CACHE, FEE_WINDOW, RAW, SEED
from plumbing.net import Client, append_jsonl, envelope, iter_jsonl, load_json, save_json, utcnow

log = logging.getLogger(__name__)

RPC_SERVERS = ("https://s2.ripple.com:51234/", "https://xrplcluster.com/", "https://s1.ripple.com:51234/")
WS_SERVERS = ("wss://xrplcluster.com/", "wss://s1.ripple.com/")
RIPPLE_EPOCH = 946_684_800  # seconds from 1970-01-01 to 2000-01-01
DROPS_PER_XRP = 1_000_000
FIRST_LEDGER = 32_570  # earliest ledger in full-history servers


def ripple_time(seconds: int) -> pd.Timestamp:
    return pd.Timestamp(seconds + RIPPLE_EPOCH, unit="s", tz="UTC")


def rpc(client: Client, method: str, params: dict[str, Any], servers=RPC_SERVERS) -> dict[str, Any]:
    """Call the first server that answers successfully."""
    last: Exception | None = None
    for url in servers:
        try:
            res = client.post_json(url, {"method": method, "params": [params]})["result"]
            if res.get("status") == "error":
                raise RuntimeError(res.get("error_message") or res.get("error"))
            return res
        except Exception as exc:  # noqa: BLE001 - fall through to the next server
            last = exc
            log.debug("xrpl %s via %s failed: %s", method, url, exc)
    raise RuntimeError(f"all XRPL servers failed for {method}: {last}")


# ------------------------------------------------------------------ parsing (pure)


def parse_header(ledger: dict[str, Any]) -> dict[str, Any]:
    return {
        "ledger_index": int(ledger["ledger_index"]),
        "close_time": ripple_time(int(ledger["close_time"])),
        "close_time_resolution": int(ledger["close_time_resolution"]),
        "n_tx": len(ledger.get("transactions", [])),
    }


def parse_transactions(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per transaction: type, fee in drops, result, and whether it moved XRP itself."""
    idx, ts = int(ledger["ledger_index"]), ripple_time(int(ledger["close_time"]))
    rows = []
    for tx in ledger.get("transactions", []):
        if not isinstance(tx, dict):
            continue
        meta = tx.get("metaData") or tx.get("meta") or {}
        amount = tx.get("Amount", tx.get("DeliverMax"))
        rows.append({
            "ledger_index": idx,
            "close_time": ts,
            "tx_type": tx.get("TransactionType"),
            "fee_drops": int(tx.get("Fee", 0)),
            "result": meta.get("TransactionResult"),
            "xrp_payment": tx.get("TransactionType") == "Payment" and isinstance(amount, str),
        })
    return rows


def span_interval(first: dict[str, Any], last: dict[str, Any]) -> float:
    """Mean seconds per ledger between two headers; the 10 s rounding error is spread over the span."""
    n = int(last["ledger_index"]) - int(first["ledger_index"])
    if n <= 0:
        raise ValueError("last ledger must come after first")
    return (int(last["close_time"]) - int(first["close_time"])) / n


def stratified_sample(lo: int, hi: int, n: int, strata: int, seed: int = SEED) -> list[int]:
    """`n` integers in [lo, hi], spread evenly over `strata` equal bins (same count per bin)."""
    rng = np.random.default_rng(seed)
    edges = np.linspace(lo, hi + 1, strata + 1).astype(int)
    per = max(1, n // strata)
    out = [int(x) for a, b in zip(edges[:-1], edges[1:], strict=True) for x in rng.integers(a, b, size=per)]
    return sorted(set(out))


def bisect_by_time(target: datetime, lo: int, hi: int, time_of: Callable[[int], datetime]) -> int:
    """First index whose time is >= target, assuming time_of is non-decreasing."""
    while lo < hi:
        mid = (lo + hi) // 2
        if time_of(mid) < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


# ------------------------------------------------------------------ fetching


def fetch_ledger(client: Client, index: int, transactions: bool, raw: Path = RAW) -> dict[str, Any]:
    kind = "full" if transactions else "header"
    path = raw / "xrpl" / kind / f"{index}.json.gz"
    if path.exists():
        return load_json(path)["payload"]
    params = {"ledger_index": index, "transactions": transactions, "expand": transactions}
    ledger = rpc(client, "ledger", params)["ledger"]
    save_json(path, envelope("xrpl", "ledger", ledger, params))
    return ledger


def ledger_time(client: Client, index: int, raw: Path = RAW) -> datetime:
    return ripple_time(int(fetch_ledger(client, index, False, raw)["close_time"])).to_pydatetime()


def window_ledgers(client: Client, window: tuple[date, date] = FEE_WINDOW, raw: Path = RAW) -> tuple[int, int]:
    latest = int(rpc(client, "ledger", {"ledger_index": "validated"})["ledger_index"])
    t0 = datetime(window[0].year, window[0].month, window[0].day, tzinfo=UTC)
    t1 = datetime(window[1].year, window[1].month, window[1].day, 23, 59, 59, tzinfo=UTC)
    first = bisect_by_time(t0, FIRST_LEDGER, latest, lambda i: ledger_time(client, i, raw))
    last = bisect_by_time(t1, first, latest, lambda i: ledger_time(client, i, raw)) - 1
    return first, last


def stream_ledgers(minutes: float, out: Path, servers=WS_SERVERS) -> int:
    """Subscribe to the ledger stream and record each ledgerClosed message with its arrival time."""
    import websocket  # optional dependency, only needed for live sampling

    deadline = time.time() + minutes * 60
    n = 0
    while time.time() < deadline:
        for url in servers:
            try:
                ws = websocket.create_connection(url, timeout=30)
                ws.send(json.dumps({"id": 1, "command": "subscribe", "streams": ["ledger"]}))
                while time.time() < deadline:
                    msg = json.loads(ws.recv())
                    if msg.get("type") == "ledgerClosed":
                        append_jsonl(out, {"received_at": utcnow().isoformat(), "server": url, "msg": msg})
                        n += 1
                ws.close()
                return n
            except Exception as exc:  # noqa: BLE001 - reconnect to the next server
                log.warning("xrpl stream %s dropped: %s", url, exc)
    return n


def parse_stream(path: Path) -> pd.DataFrame:
    rows = [{"ledger_index": int(r["msg"]["ledger_index"]), "received_at": pd.Timestamp(r["received_at"]),
             "server": r["server"], "txn_count": int(r["msg"].get("txn_count", 0)),
             "fee_base": int(r["msg"].get("fee_base", 0))} for r in iter_jsonl(path)]
    df = pd.DataFrame(rows).drop_duplicates("ledger_index").sort_values("ledger_index")
    # an interval is only valid between consecutive ledgers seen on the same connection
    consecutive = df["ledger_index"].diff().eq(1) & df["server"].eq(df["server"].shift())
    df["interval_s"] = df["received_at"].diff().dt.total_seconds().where(consecutive)
    return df.reset_index(drop=True)


# ------------------------------------------------------------------ build


def build_live(raw: Path = RAW, cache: Path = CACHE) -> dict[str, Path]:
    """Rebuild the live-interval table from every recorded stream file (offline)."""
    streams = sorted((raw / "xrpl" / "stream").glob("*.jsonl"))
    if not streams:
        return {}
    live = pd.concat([parse_stream(p) for p in streams], ignore_index=True)
    path = cache / "xrpl_live_intervals.parquet"
    live.to_parquet(path, index=False, compression="zstd")
    return {"xrpl_live": path}


def build_cache(client: Client | None = None, n_fee_ledgers: int = 1008, n_spans: int = 504, span: int = 100,
                cache: Path = CACHE, raw: Path = RAW, stream_minutes: float = 0) -> dict[str, Path]:
    client = client or Client()
    cache.mkdir(parents=True, exist_ok=True)
    first, last = window_ledgers(client, FEE_WINDOW, raw)
    log.info("fee window ledgers %d..%d", first, last)
    months = 24
    out: dict[str, Path] = {}

    tx_rows, headers = [], []
    for i, idx in enumerate(stratified_sample(first, last, n_fee_ledgers, months, SEED)):
        ledger = fetch_ledger(client, idx, True, raw)
        headers.append(parse_header(ledger))
        tx_rows += parse_transactions(ledger)
        if i % 100 == 0:
            log.info("xrpl fee sample %d/%d", i, n_fee_ledgers)
    ledgers = pd.DataFrame(headers)
    schemas.XRPL_LEDGERS.validate(ledgers)
    txs = pd.DataFrame(tx_rows)
    out["xrpl_txs"] = cache / "xrpl_tx_sample.parquet"
    txs.to_parquet(out["xrpl_txs"], index=False, compression="zstd")

    spans = []
    for idx in stratified_sample(first, last - span, n_spans, months, SEED + 1):
        a, b = fetch_ledger(client, idx, False, raw), fetch_ledger(client, idx + span, False, raw)
        spans.append({"ledger_index": idx, "close_time": ripple_time(int(a["close_time"])),
                      "mean_interval_s": span_interval(a, b), "span": span})
    out["xrpl_spans"] = cache / "xrpl_span_intervals.parquet"
    pd.DataFrame(spans).to_parquet(out["xrpl_spans"], index=False, compression="zstd")

    stream = raw / "xrpl" / "stream" / f"ledgers_{utcnow():%Y%m%d}.jsonl"
    if stream_minutes > 0:
        stream_ledgers(stream_minutes, stream)
    out.update(build_live(raw, cache))
    return out
