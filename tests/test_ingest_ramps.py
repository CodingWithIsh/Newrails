import pandas as pd
import pytest
from conftest import FakeClient

from plumbing import ingest_ramps as r
from plumbing.net import iter_jsonl


def _records(fixtures, kind):
    return list(iter_jsonl(fixtures / "snapshots" / kind / "2026-10-26.jsonl"))


def test_every_fixture_venue_parses_to_sorted_uncrossed_book(fixtures):
    for rec in _records(fixtures, "books"):
        venue = rec["source"].split(":")[1]
        bids, asks = r.parse_book(venue, rec["payload"])
        assert bids and asks, rec["source"]
        assert [p for p, _ in bids] == sorted((p for p, _ in bids), reverse=True)
        assert [p for p, _ in asks] == sorted(p for p, _ in asks)
        assert bids[0][0] < asks[0][0], rec["source"]


def test_quidax_asks_arrive_descending_and_are_reordered(fixtures):
    rec = next(x for x in _records(fixtures, "books") if x["source"] == "book:quidax:usdtngn")
    raw_asks = [float(a[0]) for a in rec["payload"]["data"]["asks"]]
    assert raw_asks == sorted(raw_asks, reverse=True)  # the venue's own order
    _, asks = r.parse_book("quidax", rec["payload"])
    assert asks[0][0] == min(raw_asks)


def test_normalise_drops_empty_levels_and_truncates():
    bids, asks = r.normalise([(1.0, 0.0), (0.9, 2.0), (0.95, 1.0)], [(1.2, 1.0), (1.1, 1.0), (0.0, 5.0)], max_levels=1)
    assert bids == [(0.95, 1.0)]
    assert asks == [(1.1, 1.0)]


def test_parse_book_errors():
    with pytest.raises(ValueError):
        r.parse_book("kraken", {"error": ["EQuery:Unknown asset pair"], "result": {}})
    with pytest.raises(ValueError):
        r.parse_book("coinsph", {"code": -100011, "msg": "Not supported symbols"})
    with pytest.raises(KeyError):
        r.parse_book("nowhere", {})


def test_book_row_fields_and_crossed_flag():
    spec = r.BookSpec("bitstamp", "x", "XRP", "GBP", "onramp_gbp")
    row = r.book_row(spec, "2026-10-26T02:00:00+00:00", {"bids": [["1.0", "2"]], "asks": [["1.02", "3"]]})
    assert row["mid"] == pytest.approx(1.01)
    assert row["spread_bps"] == pytest.approx(0.02 / 1.01 * 1e4)
    assert row["ts"].tzinfo is not None and not row["crossed"]
    crossed = r.book_row(spec, "2026-10-26T02:00:00", {"bids": [["1.03", "2"]], "asks": [["1.02", "3"]]})
    assert crossed["crossed"] and str(crossed["ts"].tz) == "UTC"


def test_parse_wise_has_one_mid_market_wise_quote_per_pair(fixtures):
    rows = []
    for rec in _records(fixtures, "wise"):
        rows += r.parse_wise(rec["payload"], rec["pulled_at"])
    df = pd.DataFrame(rows)
    wise = df[df.provider_alias == "wise"]
    assert len(wise) == len(r.WISE_PAIRS)
    assert wise.is_mid.all() and (wise.markup_pct == 0).all()
    assert (df.send_amount == 200).all()
    assert df.rate.gt(0).all()


def test_build_books_skips_errors_and_unknown_sources(tmp_path, fixtures):
    books = tmp_path / "books"
    books.mkdir()
    lines = (fixtures / "snapshots" / "books" / "2026-10-26.jsonl").read_text().splitlines()
    extra = [
        '{"source":"book:kraken:XRPGBP","pulled_at":"2026-10-26T03:00:00+00:00","payload":null,"error":"HTTPError: 503"}',
        '{"source":"book:unknown:ZZZ","pulled_at":"2026-10-26T03:00:00+00:00","payload":{}}',
        '{"source":"book:luno:USDTKES","pulled_at":"2026-10-26T03:00:00+00:00","payload":{"bids":[["x"]]}}',
        '{"torn line',
    ]
    (books / "2026-10-26.jsonl").write_text("\n".join(lines + extra) + "\n")
    df = r.build_books(tmp_path)
    assert len(df) == len(lines)
    assert not df.duplicated(["ts", "venue", "symbol"]).any()


def test_snapshot_rounds_record_failures_without_stopping(tmp_path):
    ok_book = {"bids": [["1.0", "1"]], "asks": [["1.1", "1"]]}
    specs = (r.BookSpec("bitstamp", "aaa", "A", "GBP", "onramp_gbp"), r.BookSpec("bitstamp", "bbb", "B", "GBP", "onramp_gbp"))
    client = FakeClient({
        "https://www.bitstamp.net/api/v2/order_book/aaa/": ok_book,
        "https://www.bitstamp.net/api/v2/order_book/bbb/": RuntimeError("boom"),
        r.WISE_URL: {"providers": [], "sourceCurrency": "GBP", "targetCurrency": "INR", "amount": 200},
    })
    assert r.snapshot_books(client, specs, out=tmp_path) == 1
    assert r.snapshot_wise(client, (200,), out=tmp_path) == len(r.WISE_PAIRS)
    log = r.collection_log(tmp_path)
    assert log.ok.sum() == 1 + len(r.WISE_PAIRS)
    assert log.loc[~log.ok, "error"].str.contains("boom").all()
    paths = r.build_cache(tmp_path, tmp_path / "cache")
    assert all(p.exists() for p in paths.values())


def test_collect_runs_one_round(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(r, "snapshot_books", lambda client, out: calls.append("b") or 0)
    monkeypatch.setattr(r, "snapshot_wise", lambda client, amounts, out: calls.append(tuple(amounts)) or 0)
    monkeypatch.setattr(r.time, "sleep", lambda s: None)
    ticks = iter([0.0, 0.0, 0.0, 1.0, 1e9])  # start, loop check, round start, sleep calc, loop check
    monkeypatch.setattr(r.time, "monotonic", lambda: next(ticks))
    r.collect(hours=1.0, client=object(), out=tmp_path)
    assert calls == ["b", (200, *r.WISE_EXTRA_AMOUNTS)]  # first round also pulls the extra amounts
