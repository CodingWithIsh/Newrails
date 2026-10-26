"""Solana (USDC) and Tron (USDT): fees from sampled historical blocks, timing from live sampling.

Fee mechanisms differ, so each chain is summarised in its own terms before conversion to pounds:
- Solana: 5,000 lamports per signature plus an optional priority fee (a market).
- Tron: a USDT transfer burns about 65,000 energy (130,000 to an address that has never held USDT)
  plus a few hundred bytes of bandwidth, unless the sender has staked or rented energy. The energy
  price is set by governance (history from `getenergyprices`), not by congestion.

Finality is sampled live because it is not recorded on-chain:
- Solana: the gap between the newest processed slot and the newest finalised slot. Solana moved
  from TowerBFT to Alpenglow at slot 459,653,000 (about 21 Oct 2026); live samples are after it.
- Tron: the gap between the newest block and the newest solidified (irreversible) block.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from plumbing import schemas
from plumbing.config import CACHE, FEE_WINDOW, RAW, SEED
from plumbing.ingest_xrpl import bisect_by_time, stratified_sample
from plumbing.net import Client, append_jsonl, envelope, iter_jsonl, load_json, save_json, utcnow

log = logging.getLogger(__name__)

SOLANA_RPC = "https://api.mainnet-beta.solana.com"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
LAMPORTS_PER_SIGNATURE = 5_000
LAMPORTS_PER_SOL = 1_000_000_000

TRONGRID = "https://api.trongrid.io"
USDT_TRC20 = "41a614f803b6fd780986a42c78ec9c7f77e6ded13c"  # hex form of TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t
SUN_PER_TRX = 1_000_000
TRON_SOLID_CONFIRMATIONS = 19  # a block is irreversible once 19 of 27 super representatives build on it


# ------------------------------------------------------------------ Solana


def sol_rpc(client: Client, method: str, params: list[Any]) -> Any:
    res = client.post_json(SOLANA_RPC, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if "error" in res:
        raise RuntimeError(f"solana {method}: {res['error']}")
    return res["result"]


def parse_solana_block(slot: int, block: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact per-transaction rows: total fee, its priority part, and whether USDC moved."""
    t = pd.Timestamp(block["blockTime"], unit="s", tz="UTC") if block.get("blockTime") else pd.NaT
    rows = []
    for tx in block.get("transactions", []):
        meta = tx.get("meta") or {}
        sigs = len(tx.get("transaction", {}).get("signatures", [])) or 1
        mints = {b.get("mint") for b in (meta.get("preTokenBalances") or []) + (meta.get("postTokenBalances") or [])}
        fee = int(meta.get("fee", 0))
        rows.append({
            "chain": "solana",
            "block": slot,
            "time": t,
            "tx_kind": "usdc_only" if mints == {USDC_MINT} else "usdc_mixed" if USDC_MINT in mints else "other",
            "fee_native": fee / LAMPORTS_PER_SOL,
            "priority_native": max(0, fee - LAMPORTS_PER_SIGNATURE * sigs) / LAMPORTS_PER_SOL,
            "signatures": sigs,
            "failed": meta.get("err") is not None,
        })
    return rows


def fetch_solana_block(client: Client, slot: int, raw: Path = RAW, max_skip: int = 50) -> tuple[int, dict[str, Any]]:
    """Fetch `slot`, or the next produced slot if it was skipped. Raw cache keeps only the fields used."""
    for s in range(slot, slot + max_skip):
        path = raw / "solana" / "blocks" / f"{s}.json.gz"
        if path.exists():
            return s, load_json(path)["payload"]
        try:
            params = [s, {"maxSupportedTransactionVersion": 1, "transactionDetails": "accounts", "rewards": False}]
            block = sol_rpc(client, "getBlock", params)
        except RuntimeError as exc:
            if "skipped" in str(exc).lower() or "-32007" in str(exc) or "-32009" in str(exc):
                continue
            raise
        slim = {"blockTime": block.get("blockTime"), "transactions": [
            {"meta": {k: (tx.get("meta") or {}).get(k) for k in ("fee", "err", "preTokenBalances", "postTokenBalances")},
             "transaction": {"signatures": tx["transaction"]["signatures"]}} for tx in block.get("transactions", [])]}
        for tx in slim["transactions"]:
            for k in ("preTokenBalances", "postTokenBalances"):
                tx["meta"][k] = [{"mint": b.get("mint")} for b in tx["meta"].get(k) or []]
        save_json(path, envelope("solana", "getBlock", slim, params))
        return s, slim
    raise RuntimeError(f"no produced slot in {slot}..{slot + max_skip}")


def solana_time(client: Client, slot: int) -> datetime:  # pragma: no cover - network orchestration, exercised by `make refresh`
    for s in range(slot, slot + 50):
        try:
            return datetime.fromtimestamp(sol_rpc(client, "getBlockTime", [s]), UTC)
        except RuntimeError:
            continue
    raise RuntimeError(f"no block time near slot {slot}")


def solana_window(client: Client, window: tuple[date, date] = FEE_WINDOW) -> tuple[int, int]:  # pragma: no cover - network orchestration, exercised by `make refresh`
    latest = int(sol_rpc(client, "getSlot", [{"commitment": "finalized"}]))
    lo = 250_000_000  # about February 2024, safely before the window
    t0 = datetime(window[0].year, window[0].month, window[0].day, tzinfo=UTC)
    t1 = datetime(window[1].year, window[1].month, window[1].day, 23, 59, 59, tzinfo=UTC)
    first = bisect_by_time(t0, lo, latest, lambda s: solana_time(client, s))
    last = bisect_by_time(t1, first, latest, lambda s: solana_time(client, s)) - 1
    return first, last


COMMITMENTS = ("processed", "confirmed", "finalized")


def slots_now(client: Client) -> dict[str, int]:
    """All three commitment levels in one JSON-RPC batch, so they describe the same instant.

    Asking one at a time biases the lag: slots arrive every few hundred milliseconds, so the
    finalised slot read last can be newer than the processed slot read first.
    """
    batch = [{"jsonrpc": "2.0", "id": i, "method": "getSlot", "params": [{"commitment": c}]}
             for i, c in enumerate(COMMITMENTS)]
    res = sorted(client.post_json(SOLANA_RPC, batch), key=lambda r: r["id"])
    if any("error" in r for r in res):
        raise RuntimeError(f"solana getSlot batch: {res}")
    return {c: int(r["result"]) for c, r in zip(COMMITMENTS, res, strict=True)}


def sample_solana_finality(client: Client, minutes: float, every_s: float, out: Path) -> int:  # pragma: no cover - network orchestration, exercised by `make refresh`
    n = 0
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        tick = time.time()
        rec: dict[str, Any] = {"at": utcnow().isoformat()}
        try:
            rec.update(slots_now(client))
            if n % 60 == 0:
                rec["perf"] = sol_rpc(client, "getRecentPerformanceSamples", [1])
            n += 1
        except Exception as exc:  # noqa: BLE001
            rec["error"] = str(exc)[:300]
        append_jsonl(out, rec)
        time.sleep(max(0.0, every_s - (time.time() - tick)))
    return n


# ------------------------------------------------------------------ Tron


def tron_post(client: Client, path: str, body: dict[str, Any] | None = None) -> Any:
    return client.post_json(f"{TRONGRID}{path}", body or {})


def parse_price_history(text: str) -> pd.DataFrame:
    """'0:100,1542607200000:20,...' -> effective-from timestamps and prices (sun per unit)."""
    rows = []
    for item in text.split(","):
        ts, price = item.split(":")
        rows.append({"from": pd.Timestamp(int(ts), unit="ms", tz="UTC"), "sun": int(price)})
    return pd.DataFrame(rows).sort_values("from").reset_index(drop=True)


def parse_tron_receipts(block_num: int, infos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for t in infos:
        r = t.get("receipt", {})
        is_usdt = t.get("contract_address") == USDT_TRC20
        rows.append({
            "chain": "tron",
            "block": block_num,
            "time": pd.Timestamp(int(t["blockTimeStamp"]), unit="ms", tz="UTC") if t.get("blockTimeStamp") else pd.NaT,
            "tx_kind": "usdt" if is_usdt else "other",
            "fee_native": int(t.get("fee", 0)) / SUN_PER_TRX,  # TRX actually burned by the sender
            "energy_total": int(r.get("energy_usage_total", 0)),
            "energy_burned_sun": int(r.get("energy_fee", 0)),
            "energy_from_stake": int(r.get("energy_usage", 0)) + int(r.get("origin_energy_usage", 0)),
            "net_fee_sun": int(r.get("net_fee", 0)),
            "failed": r.get("result") not in (None, "SUCCESS"),
        })
    return rows


def fetch_tron_block_infos(client: Client, num: int, raw: Path = RAW) -> list[dict[str, Any]]:
    path = raw / "tron" / "txinfo" / f"{num}.json.gz"
    if path.exists():
        return load_json(path)["payload"]
    infos = tron_post(client, "/wallet/gettransactioninfobyblocknum", {"num": num})
    keep = ("fee", "blockTimeStamp", "contract_address", "receipt")
    slim = [{k: t[k] for k in keep if k in t} for t in (infos if isinstance(infos, list) else [])]
    save_json(path, envelope("tron", "gettransactioninfobyblocknum", slim, {"num": num}))
    return slim


def tron_time(client: Client, num: int) -> datetime:  # pragma: no cover - network orchestration, exercised by `make refresh`
    b = tron_post(client, "/wallet/getblockbynum", {"num": num})
    return datetime.fromtimestamp(b["block_header"]["raw_data"]["timestamp"] / 1000, UTC)


def tron_window(client: Client, window: tuple[date, date] = FEE_WINDOW) -> tuple[int, int]:  # pragma: no cover - network orchestration, exercised by `make refresh`
    latest = tron_post(client, "/wallet/getnowblock")["block_header"]["raw_data"]["number"]
    t0 = datetime(window[0].year, window[0].month, window[0].day, tzinfo=UTC)
    t1 = datetime(window[1].year, window[1].month, window[1].day, 23, 59, 59, tzinfo=UTC)
    first = bisect_by_time(t0, 60_000_000, latest, lambda n: tron_time(client, n))
    last = bisect_by_time(t1, first, latest, lambda n: tron_time(client, n)) - 1
    return first, last


def sample_tron_finality(client: Client, minutes: float, every_s: float, out: Path) -> int:  # pragma: no cover - network orchestration, exercised by `make refresh`
    n = 0
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        tick = time.time()
        rec: dict[str, Any] = {"at": utcnow().isoformat()}
        try:
            head = tron_post(client, "/wallet/getnowblock")["block_header"]["raw_data"]
            solid = tron_post(client, "/walletsolidity/getnowblock")["block_header"]["raw_data"]
            rec.update(head=head["number"], head_ts=head["timestamp"], solid=solid["number"], solid_ts=solid["timestamp"])
            n += 1
        except Exception as exc:  # noqa: BLE001
            rec["error"] = str(exc)[:300]
        append_jsonl(out, rec)
        time.sleep(max(0.0, every_s - (time.time() - tick)))
    return n


# ------------------------------------------------------------------ live-sample parsing (pure)


def parse_solana_live(path: Path) -> pd.DataFrame:
    rows = [r for r in iter_jsonl(path) if "error" not in r]
    df = pd.DataFrame(rows).rename(columns={"at": "sampled_at"})  # "at" would shadow DataFrame.at
    df["sampled_at"] = pd.to_datetime(df["sampled_at"])
    df["lag_confirmed"] = df["processed"] - df["confirmed"]
    df["lag_finalized"] = df["processed"] - df["finalized"]
    return df.drop(columns=["perf"], errors="ignore")


def solana_slot_seconds(path: Path) -> pd.DataFrame:
    """Seconds per slot from the node's own one-minute performance samples."""
    rows = []
    for r in iter_jsonl(path):
        for p in r.get("perf") or []:
            if p.get("numSlots"):
                rows.append({"slot": p["slot"], "slot_s": p["samplePeriodSecs"] / p["numSlots"],
                             "tx_per_s": p["numTransactions"] / p["samplePeriodSecs"]})
    return pd.DataFrame(rows).drop_duplicates("slot")


def parse_tron_live(path: Path) -> pd.DataFrame:
    rows = [r for r in iter_jsonl(path) if "error" not in r]
    df = pd.DataFrame(rows).rename(columns={"at": "sampled_at"})
    df["sampled_at"] = pd.to_datetime(df["sampled_at"])
    df["lag_blocks"] = df["head"] - df["solid"]
    df["lag_s"] = (df["head_ts"] - df["solid_ts"]) / 1000
    return df


def tron_block_intervals(live: pd.DataFrame) -> pd.Series:
    """Seconds between distinct head blocks seen consecutively (3 s slots; a missed slot shows as 6 s)."""
    heads = live.drop_duplicates("head").sort_values("head")
    consecutive = heads["head"].diff().eq(1)
    return (heads["head_ts"].diff() / 1000).where(consecutive).dropna().rename("interval_s")


# ------------------------------------------------------------------ build


def build_live(raw: Path = RAW, cache: Path = CACHE) -> dict[str, Path]:
    """Rebuild finality and slot-time tables from every recorded live-sample file (offline)."""
    out: dict[str, Path] = {}
    for name, parse, pattern in (("solana_live", parse_solana_live, "solana/live/*.jsonl"),
                                 ("tron_live", parse_tron_live, "tron/live/*.jsonl"),
                                 ("solana_slot_seconds", solana_slot_seconds, "solana/live/*.jsonl")):
        files = sorted(raw.glob(pattern))
        if files:
            out[name] = cache / f"{name}.parquet"
            pd.concat([parse(p) for p in files], ignore_index=True).to_parquet(out[name], index=False)
    return out


def build_cache(client: Client | None = None, n_solana: int = 120, n_tron: int = 480,
                cache: Path = CACHE, raw: Path = RAW) -> dict[str, Path]:  # pragma: no cover - network orchestration, exercised by `make refresh`
    client = client or Client()
    cache.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    rows: list[dict[str, Any]] = []

    s_first, s_last = solana_window(client)
    log.info("solana window slots %d..%d", s_first, s_last)
    for i, slot in enumerate(stratified_sample(s_first, s_last, n_solana, 24, SEED + 2)):
        s, block = fetch_solana_block(client, slot, raw)
        rows += parse_solana_block(s, block)
        if i % 20 == 0:
            log.info("solana %d/%d", i, n_solana)

    t_first, t_last = tron_window(client)
    log.info("tron window blocks %d..%d", t_first, t_last)
    for i, num in enumerate(stratified_sample(t_first, t_last, n_tron, 24, SEED + 3)):
        rows += parse_tron_receipts(num, fetch_tron_block_infos(client, num, raw))
        if i % 50 == 0:
            log.info("tron %d/%d", i, n_tron)

    fees = pd.DataFrame(rows)
    schemas.CHAIN_FEES.validate(fees)
    out["chain_fees"] = cache / "chain_fee_sample.parquet"
    fees.to_parquet(out["chain_fees"], index=False, compression="zstd")

    prices = {}
    for name, path in (("energy", "/wallet/getenergyprices"), ("bandwidth", "/wallet/getbandwidthprices")):
        payload = client.get_json(f"{TRONGRID}{path}")
        save_json(raw / "tron" / f"{name}_prices.json.gz", envelope("tron", path, payload))
        prices[name] = parse_price_history(payload["prices"]).assign(resource=name)
    out["tron_prices"] = cache / "tron_resource_prices.parquet"
    pd.concat(prices.values(), ignore_index=True).to_parquet(out["tron_prices"], index=False)

    out.update(build_live(raw, cache))
    return out
