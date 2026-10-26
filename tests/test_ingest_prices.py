import hashlib
import io
import zipfile
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest
from conftest import FakeClient

from plumbing import ingest_prices as p
from plumbing import schemas


def test_months_inclusive_across_year_end():
    assert p.months(date(2025, 11, 3), date(2026, 2, 1)) == ["2025-11", "2025-12", "2026-01", "2026-02"]


@pytest.mark.parametrize("value,unit", [(1_700_000_000, "s"), (1_700_000_000_000, "ms"), (1_700_000_000_000_000, "us")])
def test_epoch_unit_inferred_from_magnitude(value, unit):
    assert p.to_utc([value])[0] == pd.Timestamp(1_700_000_000, unit="s", tz="UTC")


def _kline_csv(times, header=False):
    rows = [f"{t},1.0,1.2,0.9,1.1,100,{t + 59_999},110,5,50,55,0" for t in times]
    if header:
        rows.insert(0, ",".join(p.KLINE_COLS))
    return "\n".join(rows).encode()


def test_binance_csv_handles_microseconds_and_headers():
    ms = p.parse_binance_csv(_kline_csv([1_704_067_200_000, 1_704_067_260_000]))
    us = p.parse_binance_csv(_kline_csv([1_735_689_600_000_000], header=True))
    assert ms.ts.iloc[0] == pd.Timestamp("2024-01-01", tz="UTC") and len(ms) == 2
    assert us.ts.iloc[0] == pd.Timestamp("2025-01-01", tz="UTC") and len(us) == 1
    schemas.CANDLES.validate(ms)


def test_binance_month_download_checks_checksum(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("XRPUSDT-1m-2026-09.csv", _kline_csv([1_788_220_800_000_000]))
    blob = buf.getvalue()
    good = f"{hashlib.sha256(blob).hexdigest()}  XRPUSDT-1m-2026-09.zip"

    class Resp:
        def __init__(self, content=b"", text=""):
            self.content, self.text = content, text

    class Client:
        def __init__(self, checksum):
            self.checksum, self.calls = checksum, 0

        def get(self, url, params=None):
            self.calls += 1
            return Resp(text=self.checksum) if url.endswith("CHECKSUM") else Resp(content=blob)

    with pytest.raises(ValueError, match="checksum"):
        p.fetch_binance_month(Client("0" * 64), "XRPUSDT", "1m", "2026-09", raw=tmp_path)
    c = Client(good)
    path = p.fetch_binance_month(c, "XRPUSDT", "1m", "2026-09", raw=tmp_path)
    assert p.read_binance_zip(path).close.iloc[0] == 1.1
    p.fetch_binance_month(c, "XRPUSDT", "1m", "2026-09", raw=tmp_path)
    assert c.calls == 2  # second call is served from the verified cache


def _bitstamp(start, n, step, price=1.0):
    return {"data": {"ohlc": [{"timestamp": str(start + i * step), "open": price, "high": price, "low": price,
                              "close": price, "volume": "1"} for i in range(n)]}}


def test_bitstamp_paging_skips_pre_listing_pages(tmp_path):
    start = int(datetime(2021, 1, 1, tzinfo=UTC).timestamp())
    listed = start + 1000 * 3600

    def answer():
        cursor = client.calls[-1][1]["start"]
        return _bitstamp(cursor, 1000, 3600) if cursor >= listed else _bitstamp(0, 0, 3600)

    client = FakeClient({p.BITSTAMP_OHLC.format(pair="usdtusd"): answer})
    end = datetime.fromtimestamp(listed + 1500 * 3600, UTC)
    df = p.fetch_bitstamp(client, "usdtusd", 3600, datetime.fromtimestamp(start, UTC), end, raw=tmp_path)
    assert df.ts.min() == pd.Timestamp(listed, unit="s", tz="UTC")
    assert len(df) == 1500 and df.ts.is_monotonic_increasing


def _hourly(prices, start="2023-03-10"):
    ts = pd.date_range(start, periods=len(prices), freq="h", tz="UTC")
    a = np.asarray(prices, dtype=float)
    return pd.DataFrame({"ts": ts, "open": a, "high": a, "low": a, "close": a, "volume": 1.0})


def test_bad_prints_are_dropped_and_counted():
    df = _hourly([1.0, 2959.0, 0.999, 0.3])
    clean, n = p.drop_bad_prints(df)
    assert n == 2 and clean.close.tolist() == [1.0, 0.999]


def test_peg_episodes_merge_nearby_hours_and_report_worst_price():
    prices = [1.0] * 5 + [0.99, 0.95, 0.88] + [1.0] * 10 + [0.992] + [1.0] * 40 + [1.007] + [1.0] * 3
    ep = p.peg_episodes(_hourly(prices), threshold=0.005, merge_gap_h=24)
    assert len(ep) == 2
    assert ep.hours.tolist() == [4, 1]
    assert ep.worst_price.iloc[0] == pytest.approx(0.88) and ep.max_dev.iloc[0] == pytest.approx(0.12)
    assert ep.worst_price.iloc[1] == pytest.approx(1.007)
    assert p.peg_episodes(_hourly([1.0] * 10)).empty


def test_frankfurter_and_fawaz_parsing():
    fr = p.parse_frankfurter({"base": "USD", "rates": {"2025-09-30": {"INR": 88.7, "GBP": 0.744}}})
    assert set(fr.quote) == {"INR", "GBP"} and (fr.source == "ecb").all()
    fa = p.parse_fawaz({"date": "2025-09-30", "usd": {"ngn": 1480.1, "kes": 129.2}}, "usd", ["ngn", "kes", "pkr"])
    assert [r["quote"] for r in fa] == ["NGN", "KES"]
    schemas.FX_DAILY.validate(pd.concat([fr, pd.DataFrame(fa)], ignore_index=True))


def test_rpw_fx_anchors_use_us_corridors_median():
    rpw = pd.DataFrame({"source_code": ["USA", "USA", "GBR", "USA"], "period": ["2025_3Q"] * 3 + ["2019_1Q"],
                        "destination_code": ["NGA", "NGA", "NGA", "NGA"],
                        "date": pd.to_datetime(["2025-08-20"] * 4), "interbank_fx": [1500.0, 1510.0, 2000.0, 300.0]})
    a = p.rpw_fx_anchors(rpw)
    assert len(a) == 1 and a.rate.iloc[0] == 1505.0


@pytest.mark.parametrize("market,payload", [
    ("wazirx:usdtinr", [[1700000000, "83.1", "83.5", "82.9", "83.2", "1000"]]),
    ("coindcx:I-USDT_INR", [{"time": 1700000000000, "open": 83.1, "high": 83.5, "low": 82.9, "close": 83.2, "volume": 1000}]),
    ("quidax:usdtngn", {"data": [[1700000000, 1100, 1110, 1090, 1105, 50]]}),
    ("coinsph:USDTPHP", [[1700000000000, "56.1", "56.2", "56.0", "56.1", "10", 1700086399999]]),
    ("bitso:usdt_mxn", {"payload": [{"bucket_start_time": 1700000000000, "first_rate": "17.2", "max_rate": "17.3",
                                     "min_rate": "17.1", "last_rate": "17.25", "volume": "100"}]}),
])
def test_local_market_parsers(market, payload):
    df = p.parse_local(market, payload)
    assert df.ts.iloc[0] == pd.Timestamp(1700000000, unit="s", tz="UTC")
    assert df.close.iloc[0] > 0
    schemas.CANDLES.validate(df)


def test_local_parser_rejects_unknown_market():
    with pytest.raises(KeyError):
        p.parse_local("nowhere:x", [])


def test_local_premium_against_official_rate():
    local = pd.DataFrame({"ts": pd.to_datetime(["2025-09-29", "2025-09-30", "2025-10-10"], utc=True),
                          "close": [94.0, 94.5, 95.0]})
    fx = pd.DataFrame({"date": pd.to_datetime(["2025-09-29", "2025-09-30"]), "base": "USD", "quote": "INR",
                       "rate": [88.0, 88.5], "source": "ecb"})
    prem = p.local_premium(local, fx, "INR")
    assert len(prem) == 2  # the 10 October close has no official rate within 4 days
    assert prem.premium.tolist() == pytest.approx([94.0 / 88.0 - 1, 94.5 / 88.5 - 1])


def test_compact_minutes_leaves_gaps_as_nan():
    df = pd.DataFrame({"ts": pd.to_datetime(["2026-01-01 00:00", "2026-01-01 00:01", "2026-01-01 00:04"], utc=True),
                       "close": [1.0, 1.1, 1.2]})
    out = p.compact_minutes(df)
    assert len(out) == 5 and out.close.isna().sum() == 2 and out.close.dtype == np.float32
