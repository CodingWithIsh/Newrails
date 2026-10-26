from datetime import date

import pytest
from pydantic import ValidationError

from plumbing import schemas
from plumbing.ingest_ramps import fee_lookup, load_availability, load_fees


def test_fee_file_is_valid_and_unique():
    fees = load_fees()
    assert len(fee_lookup(fees)) == len(fees)
    assert all(f.sources for f in fees)
    assert all(s.accessed <= date(2026, 10, 26) for f in fees for s in f.sources)


def test_every_unverified_fee_is_a_range_or_documented():
    for f in load_fees():
        if not f.verified:
            assert f.high > f.low or "assumed" in (f.sources[0].note or "").lower() or f.high == 0, f


def test_availability_file_is_valid():
    rows = load_availability()
    assert {r.status for r in rows} <= {"yes", "no", "unverified"}
    assert any(r.venue == "none_pk" and r.status == "no" for r in rows)


SRC = [{"url": "https://example.com", "accessed": "2026-10-26"}]


@pytest.mark.parametrize("bad", [
    dict(low=-0.1, high=0.2),                          # negative fee
    dict(low=0.5, high=0.2),                           # high below low
    dict(unit="GBP"),                                  # percentage fee in currency units
    dict(leg="withdraw_crypto"),                       # crypto withdrawal without a network
    dict(sources=[{"url": "not a url", "accessed": "2026-10-26"}]),
    dict(colour="red"),                                # unknown field
])
def test_fee_schema_rejects_bad_entries(bad):
    row = dict(provider="x", leg="trade", asset="XRP", kind="pct", low=0.1, high=0.2, unit="%", sources=SRC)
    row.update(bad)
    with pytest.raises(ValidationError):
        schemas.FeeEntry(**row)


def test_duplicate_fee_keys_rejected():
    row = dict(provider="x", leg="trade", asset="XRP", kind="pct", low=0.1, high=0.2, unit="%", sources=SRC)
    with pytest.raises(ValueError, match="duplicate"):
        fee_lookup([schemas.FeeEntry(**row), schemas.FeeEntry(**row)])
