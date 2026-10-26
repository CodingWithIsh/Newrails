import numpy as np
import pandas as pd
import pytest

from plumbing import ingest_rpw as r
from plumbing import schemas
from plumbing.config import CORRIDORS_GBP, Corridor


@pytest.fixture(scope="module")
def rpw() -> pd.DataFrame:
    return r.load()


# ---------------------------------------------------------------- regression against published figures


def test_reproduces_published_global_average_q3_2025(rpw):
    # World Bank RPW, Q3 2025: global average cost of sending $200 = 6.36%
    assert r.global_average(rpw) == pytest.approx(6.36, abs=0.005)


def test_reproduces_project_one_uk_average_q3_2025(rpw):
    # Numbers Behind the Money, article 2: UK average for £120 = 4.61%
    assert r.country_average(rpw, "GBR") == pytest.approx(4.61, abs=0.005)


def test_published_total_equals_fee_share_plus_margin(rpw):
    assert r.check_total_identity(rpw) > 0.999


# ---------------------------------------------------------------- schema


def test_cache_matches_schema(rpw):
    schemas.RPW.validate(r.load(transparent_only=False))
    assert set(rpw["source_code"]) >= {"GBR", "USA"}
    assert (rpw.loc[rpw.source_code == "GBR", "amount_1"] == 120).all()
    assert (rpw.loc[rpw.source_code == "GBR", "amount_2"] == 300).all()


def test_all_corridors_present(rpw):
    for c in CORRIDORS_GBP:
        assert len(r.corridor_quotes(rpw, c)) >= 20, c


def test_schema_rejects_bad_frames():
    good = pd.DataFrame({"x": [1.0, 2.0], "k": ["a", "b"]})
    s = schemas.FrameSchema("t", {"x": schemas.Col("float", min=0), "k": schemas.Col("str")}, key=("k",), min_rows=2)
    s.validate(good)
    for bad, msg in [
        (good.assign(x=[-1.0, 2.0]), "below"),
        (good.assign(x=[np.nan, 2.0]), "nulls"),
        (good.assign(k=["a", "a"]), "duplicate"),
        (good.drop(columns="k"), "missing"),
        (good.head(1), "rows"),
        (good.assign(x=["1", "2"]), "dtype"),
    ]:
        with pytest.raises(schemas.SchemaError, match=msg):
            s.validate(bad)


# ---------------------------------------------------------------- cleaning


def test_clean_renames_types_and_flags():
    raw = pd.DataFrame({
        "id": ["7"], "period": ["2025_3Q"], "date": ["2025-08-20"], "source_code": ["GBR"], "source_name": ["UK"],
        "destination_code": ["GMB"], "destination_name": ["Gambia, The"], "firm": [" Acme "], "firm_type": ["Bank"],
        "payment instrument": ["Cash"], "access point": ["Agent"], "speed actual": ["Same day"],
        "pickup method": ["Cash"], "receiving network coverage": ["Urban"], "transparent": [" Yes"],
        "cc1 lcu code": ["GBP"], "cc1 lcu amount": [120], "cc1 lcu fee": ["2.4"], "cc1 fx margin": ["1.0"],
        "cc1 total cost %": ["3.0"], "cc1 lcu fx rate": ["1"], "cc2 lcu amount": [300], "cc2 lcu fee": ["n/a"],
        "cc2 fx margin": [None], "cc2 total cost %": [None], "cc2 lcu fx rate": [None], "inter lcu bank fx": ["1.01"],
    })
    df = r.clean(raw)
    row = df.iloc[0]
    assert row["destination_name"] == "The Gambia" and row["firm"] == "Acme" and bool(row["transparent"])
    assert row["fee_1"] == 2.4 and np.isnan(row["fee_2"]) and row["id"] == 7
    assert list(df.columns) == r.KEEP


# ---------------------------------------------------------------- interpolation


def _svc(**kw):
    base = dict(amount_1=120.0, amount_2=300.0, fee_1=2.0, fee_2=2.0, margin_1=1.0, margin_2=1.0)
    base.update(kw)
    return pd.DataFrame([base])


def test_flat_fee_interpolates_to_its_share_of_200():
    out = r.interpolate(_svc(), 200).iloc[0]
    assert out["fee"] == 2.0 and out["fee_pct"] == pytest.approx(1.0) and out["total"] == pytest.approx(2.0)
    assert out["interp"] == "linear"


def test_hand_computed_interpolation():
    # fee 3.00 -> 4.80 and margin 1.2 -> 0.3 between £120 and £300; at £200 the weight is 80/180 = 4/9
    out = r.interpolate(_svc(fee_1=3.0, fee_2=4.8, margin_1=1.2, margin_2=0.3), 200).iloc[0]
    assert out["fee"] == pytest.approx(3.8)
    assert out["margin"] == pytest.approx(0.8)
    assert out["total"] == pytest.approx(3.8 / 200 * 100 + 0.8)


def test_interpolation_hits_the_quotes_exactly_at_the_ends():
    svc = _svc(fee_1=3.0, fee_2=4.8, margin_1=1.2, margin_2=0.3)
    assert r.interpolate(svc, 120).iloc[0]["total"] == pytest.approx(3.0 / 120 * 100 + 1.2)
    assert r.interpolate(svc, 300).iloc[0]["total"] == pytest.approx(4.8 / 300 * 100 + 0.3)


def test_no_extrapolation_outside_the_quotes():
    svc = _svc(fee_1=3.0, fee_2=4.8, margin_1=1.2, margin_2=0.3)
    lo, hi = r.interpolate(svc, 50).iloc[0], r.interpolate(svc, 1000).iloc[0]
    assert lo["fee"] == 3.0 and lo["margin"] == 1.2 and lo["interp"] == "held_flat"
    assert hi["fee"] == pytest.approx(4.8) and hi["margin"] == pytest.approx(0.3)


def test_missing_second_quote_uses_first_and_flags():
    out = r.interpolate(_svc(fee_2=np.nan, margin_2=np.nan), 200).iloc[0]
    assert out["fee"] == 2.0 and out["margin"] == 1.0 and out["interp"] == "first_quote_only"


def test_zero_fee_service_cost_is_its_margin():
    out = r.interpolate(_svc(fee_1=0.0, fee_2=0.0, margin_1=0.5, margin_2=0.5), 200).iloc[0]
    assert out["total"] == pytest.approx(0.5)


# ---------------------------------------------------------------- benchmarks


def _corridor_frame():
    rows = [
        # firm, access, pickup, fee_1, margin_1
        ("NegPromo", "Internet", "Bank account", 0.0, -0.5),
        ("CheapApp", "Internet", "Bank account", 0.0, 0.3),
        ("Wallet", "Internet", "Mobile wallet", 1.0, 0.6),
        ("MidApp", "Internet", "Own/partner Bank account", 2.0, 1.0),
        ("Agent", "Agent", "Cash", 5.0, 3.0),
    ]
    df = pd.DataFrame(rows, columns=["firm", "access_point", "pickup_method", "fee_1", "margin_1"])
    return df.assign(period="2025_3Q", source_code="GBR", destination_name="Testland", amount_1=120.0,
                     amount_2=300.0, fee_2=df["fee_1"], margin_2=df["margin_1"], speed="Same day")


def test_benchmarks_exclude_negative_margins_and_cash():
    c = Corridor("GBR", "TST", "Testland", "GBP", "TST")
    b = r.benchmarks(_corridor_frame(), c, 200)
    assert b["B1_firm"] == "CheapApp" and b["B1"] == pytest.approx(0.3)
    assert b["n_digital"] == 4
    digital_totals = [-0.5, 0.3, 1.0 / 2 + 0.6, 2.0 / 2 + 1.0]
    assert b["B2"] == pytest.approx(np.median(digital_totals))
    assert b["B3"] == pytest.approx(np.mean(digital_totals + [5.0 / 2 + 3.0]))
    assert b["min_raw"] == pytest.approx(-0.5)


def test_benchmarks_of_empty_corridor_are_nan():
    c = Corridor("GBR", "NON", "Nowhere", "GBP", "XXX")
    b = r.benchmarks(_corridor_frame(), c, 200)
    assert np.isnan(b["B1"]) and np.isnan(b["B2"]) and np.isnan(b["B3"]) and b["n_services"] == 0


def test_speed_distribution_sums_to_one(rpw):
    for c in CORRIDORS_GBP:
        assert r.speed_distribution(rpw, c).sum() == pytest.approx(1.0)
