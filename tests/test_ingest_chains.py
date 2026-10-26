import json
from datetime import UTC, datetime

import pandas as pd
import pytest
from conftest import FakeClient

from plumbing import ingest_chain as ch
from plumbing import ingest_xrpl as x
from plumbing import schemas


def _load(fixtures, name):
    return json.loads((fixtures / "chain" / name).read_text())


# ---------------------------------------------------------------- XRPL


def test_ripple_epoch_conversion(fixtures):
    h = _load(fixtures, "xrpl_header_95000100.json")
    assert x.ripple_time(int(h["close_time"])) == pd.Timestamp(h["close_time_iso"])


def test_parse_xrpl_transactions(fixtures):
    led = _load(fixtures, "xrpl_ledger_95000000.json")
    rows = pd.DataFrame(x.parse_transactions(led))
    assert len(rows) == 5
    assert rows.xrp_payment.sum() == 2  # two XRP payments, one IOU payment, two others
    assert (rows.tx_type == "Payment").sum() == 3
    assert (rows.fee_drops >= 10).all() and rows.result.notna().all()
    head = x.parse_header(led)
    assert head["n_tx"] == 5 and head["close_time_resolution"] == 10
    schemas.XRPL_LEDGERS.validate(pd.DataFrame([head]))


def test_span_interval_spreads_rounding(fixtures):
    a, b = _load(fixtures, "xrpl_ledger_95000000.json"), _load(fixtures, "xrpl_header_95000100.json")
    secs = x.span_interval(a, b)
    assert 3.0 < secs < 5.0  # XRPL closes a ledger every few seconds
    with pytest.raises(ValueError):
        x.span_interval(b, a)


def test_stratified_sample_is_seeded_and_spread():
    s1 = x.stratified_sample(0, 23_999, 48, 24, seed=1)
    assert s1 == x.stratified_sample(0, 23_999, 48, 24, seed=1)
    assert s1 != x.stratified_sample(0, 23_999, 48, 24, seed=2)
    bins = pd.Series(s1) // 1000
    assert bins.nunique() == 24 and bins.value_counts().max() <= 2
    assert min(s1) >= 0 and max(s1) <= 23_999


def test_bisect_by_time_finds_first_at_or_after():
    times = {i: datetime(2025, 1, 1, tzinfo=UTC).replace(minute=i // 10) for i in range(600)}
    target = datetime(2025, 1, 1, 0, 30, tzinfo=UTC)
    assert x.bisect_by_time(target, 0, 599, times.__getitem__) == 300


def test_rpc_falls_back_to_next_server():
    ok = {"result": {"status": "success", "ledger_index": 5}}
    client = FakeClient({x.RPC_SERVERS[0]: RuntimeError("down"), x.RPC_SERVERS[1]: ok})
    assert x.rpc(client, "ledger", {})["ledger_index"] == 5
    bad = FakeClient({}, default={"result": {"status": "error", "error": "lgrNotFound"}})
    with pytest.raises(RuntimeError, match="all XRPL servers failed"):
        x.rpc(bad, "ledger", {})


def test_fetch_ledger_caches(tmp_path, fixtures):
    led = _load(fixtures, "xrpl_ledger_95000000.json")
    client = FakeClient({}, default={"result": {"status": "success", "ledger": led}})
    a = x.fetch_ledger(client, 95000000, True, raw=tmp_path)
    b = x.fetch_ledger(client, 95000000, True, raw=tmp_path)
    assert a == b and len(client.calls) == 1


def test_parse_stream_only_measures_consecutive_ledgers(tmp_path):
    p = tmp_path / "s.jsonl"
    msgs = [(100, "2026-10-26T00:00:00+00:00", "a"), (101, "2026-10-26T00:00:04+00:00", "a"),
            (103, "2026-10-26T00:00:12+00:00", "a"), (104, "2026-10-26T00:00:15.500+00:00", "b"),
            (105, "2026-10-26T00:00:19+00:00", "b"), (105, "2026-10-26T00:00:19.1+00:00", "b")]
    p.write_text("\n".join(json.dumps({"received_at": t, "server": s, "msg": {"ledger_index": i, "txn_count": 1}})
                           for i, t, s in msgs))
    df = x.parse_stream(p)
    assert len(df) == 5
    assert df.interval_s.dropna().tolist() == [4.0, 3.5]


# ---------------------------------------------------------------- Solana


def test_parse_solana_block(fixtures):
    f = _load(fixtures, "solana_block_slim.json")
    rows = pd.DataFrame(ch.parse_solana_block(f["slot"], f["block"]))
    schemas.CHAIN_FEES.validate(rows)
    assert rows.tx_kind.tolist().count("usdc_only") == 1 and rows.tx_kind.tolist().count("usdc_mixed") == 1
    two_sig = rows[rows.signatures == 2].iloc[0]
    assert two_sig.fee_native == pytest.approx(20038 / 1e9)
    assert two_sig.priority_native == pytest.approx((20038 - 10000) / 1e9)
    assert (rows.priority_native <= rows.fee_native).all()


def test_slots_now_uses_one_batch():
    batch = [{"id": 2, "result": 9}, {"id": 0, "result": 10}, {"id": 1, "result": 9}]
    client = FakeClient({ch.SOLANA_RPC: batch})
    assert ch.slots_now(client) == {"processed": 10, "confirmed": 9, "finalized": 9}
    assert len(client.calls) == 1 and len(client.calls[0][1]) == 3
    with pytest.raises(RuntimeError):
        ch.slots_now(FakeClient({ch.SOLANA_RPC: [{"id": 0, "error": {}}, {"id": 1, "result": 1}, {"id": 2, "result": 1}]}))


def test_fetch_solana_block_skips_skipped_slots(tmp_path, fixtures):
    f = _load(fixtures, "solana_block_slim.json")
    answers = iter([{"error": {"code": -32007, "message": "Slot 1 was skipped"}}, {"result": f["block"]}])
    client = FakeClient({ch.SOLANA_RPC: lambda: next(answers)})
    slot, block = ch.fetch_solana_block(client, 1, raw=tmp_path)
    assert slot == 2 and len(block["transactions"]) == len(f["block"]["transactions"])
    assert ch.fetch_solana_block(client, 2, raw=tmp_path)[0] == 2  # second read comes from the cache


def test_solana_live_parsing(tmp_path):
    p = tmp_path / "live.jsonl"
    p.write_text("\n".join([
        json.dumps({"at": "2026-10-26T00:00:00+00:00", "processed": 10, "confirmed": 9, "finalized": 9,
                    "perf": [{"slot": 10, "numSlots": 300, "samplePeriodSecs": 60, "numTransactions": 6000}]}),
        json.dumps({"at": "2026-10-26T00:00:02+00:00", "error": "timeout"}),
        json.dumps({"at": "2026-10-26T00:00:04+00:00", "processed": 30, "confirmed": 30, "finalized": 29}),
    ]))
    live = ch.parse_solana_live(p)
    assert live.lag_finalized.tolist() == [1, 1] and live.lag_confirmed.tolist() == [1, 0]
    slot_s = ch.solana_slot_seconds(p)
    assert slot_s.slot_s.iloc[0] == pytest.approx(0.2) and slot_s.tx_per_s.iloc[0] == pytest.approx(100)


# ---------------------------------------------------------------- Tron


def test_parse_tron_receipts(fixtures):
    infos = _load(fixtures, "tron_txinfo_87000000.json")
    rows = pd.DataFrame(ch.parse_tron_receipts(87000000, infos))
    schemas.CHAIN_FEES.validate(rows)
    usdt = rows[rows.tx_kind == "usdt"]
    assert len(usdt) == 4
    assert set(usdt.energy_total) >= {64285, 130285}  # existing holder vs first-time holder
    assert usdt.failed.sum() == 1
    assert (rows.fee_native >= 0).all()


def test_parse_price_history():
    df = ch.parse_price_history("0:100,1542607200000:20,1756468800000:100")
    assert df.sun.tolist() == [100, 20, 100]
    assert df["from"].iloc[-1] == pd.Timestamp("2025-08-29 12:00", tz="UTC")


def test_tron_live_lag_and_intervals(tmp_path):
    p = tmp_path / "t.jsonl"
    recs = [{"at": "2026-10-26T00:00:00+00:00", "head": 100, "head_ts": 0, "solid": 81, "solid_ts": -57000},
            {"at": "2026-10-26T00:00:03+00:00", "head": 101, "head_ts": 3000, "solid": 82, "solid_ts": -54000},
            {"at": "2026-10-26T00:00:06+00:00", "head": 101, "head_ts": 3000, "solid": 82, "solid_ts": -54000},
            {"at": "2026-10-26T00:00:09+00:00", "head": 102, "head_ts": 9000, "solid": 83, "solid_ts": -51000},
            {"at": "2026-10-26T00:00:12+00:00", "error": "503"}]
    p.write_text("\n".join(json.dumps(r) for r in recs))
    live = ch.parse_tron_live(p)
    assert live.lag_blocks.unique().tolist() == [19]
    assert live.lag_s.tolist()[:2] == [57.0, 57.0]
    assert ch.tron_block_intervals(live).tolist() == [3.0, 6.0]  # a missed slot shows as 6 s


def test_tron_txinfo_cache(tmp_path, fixtures):
    infos = _load(fixtures, "tron_txinfo_87000000.json")
    client = FakeClient({ch.TRONGRID + "/wallet/gettransactioninfobyblocknum": infos})
    a = ch.fetch_tron_block_infos(client, 87000000, raw=tmp_path)
    b = ch.fetch_tron_block_infos(client, 87000000, raw=tmp_path)
    assert a == b and len(client.calls) == 1
