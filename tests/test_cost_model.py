import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from plumbing import cost_model as cm
from plumbing.config import Corridor
from plumbing.ingest_ramps import fee_lookup, load_fees

# ---------------------------------------------------------------- order-book walking


def test_walk_asks_hand_computed():
    # 10 units at 2.0 then 10 at 3.0: spending 35 buys 10 + 15/3 = 15 units
    assert cm.walk_asks([2.0, 3.0], [10, 10], 35) == pytest.approx(15.0)
    assert cm.walk_asks([2.0, 3.0], [10, 10], 20) == pytest.approx(10.0)
    assert math.isnan(cm.walk_asks([2.0], [10], 25))  # book too thin
    assert cm.walk_asks([2.0], [10], 0) == 0
    with pytest.raises(ValueError):
        cm.walk_asks([2.0], [10], -1)


def test_walk_bids_hand_computed():
    assert cm.walk_bids([5.0, 4.0], [1, 10], 3) == pytest.approx(5 + 2 * 4)
    assert math.isnan(cm.walk_bids([5.0], [1], 2))
    with pytest.raises(ValueError):
        cm.walk_bids([5.0], [1], -1)


def test_book_mid_and_empty_side():
    assert cm.Book([1.0], [1], [1.2], [1]).mid == pytest.approx(1.1)
    assert math.isnan(cm.Book([], [], [1.2], [1]).mid)


# ---------------------------------------------------------------- one transfer, by hand

GBP_INR = cm.Mids(send_local=127.0, send_usd=1.27, usd_local=100.0)


def test_zero_fee_flat_books_cost_nothing():
    on = cm.Book.flat(1 / 1.27)  # USDT at exactly the official GBP/USD rate
    off = cm.Book.flat(100.0)  # USDT/INR at exactly the official USD/INR rate
    res = cm.simulate(200, "USDT", on, off, GBP_INR, cm.RouteFees())
    assert res.cost_pct == pytest.approx(0.0, abs=1e-9)
    assert all(abs(v) < 1e-9 for v in res.contributions().values())


def test_stablecoin_route_hand_computed():
    fees = cm.RouteFees(onramp_pct=0.2, withdraw_fixed_asset=1.0, offramp_pct=0.5, payout_fixed_local=25.0)
    on = cm.Book([0.78], [1e6], [0.79], [1e6])  # mid 0.785 GBP per USDT
    off = cm.Book([105.0], [1e6], [106.0], [1e6])  # mid 105.5 INR per USDT (a 5.5% premium)
    res = cm.simulate(200, "USDT", on, off, GBP_INR, fees)
    units = 200 * (1 - 0.002) / 0.79 - 1.0
    expected = units * 105.0 * (1 - 0.005) - 25.0
    assert res.received == pytest.approx(expected)
    assert res.cost_pct == pytest.approx(100 * (1 - expected / (200 * 127.0)))
    con = res.contributions()
    assert sum(con.values()) == pytest.approx(res.cost_pct)
    assert con["premium"] < 0  # selling above the official rate is a gain for the recipient
    assert res.cost_excluding("premium") > res.cost_pct


def test_xrp_route_premium_is_cross_market_basis():
    on = cm.Book([0.96], [1e6], [0.97], [1e6])  # XRP/GBP
    off = cm.Book([0.965 * 127.0], [1e6], [0.965 * 127.0 + 1], [1e6])
    res = cm.simulate(200, "XRP", on, off, GBP_INR, cm.RouteFees())
    prem = next(leg for leg in res.legs if leg.category == "premium")
    assert prem.factor == pytest.approx(off.mid / (on.mid * 127.0))


def test_swap_routes_reconcile():
    on = cm.Book([0.78], [1e6], [0.79], [1e6])
    swap = cm.Book([0.999], [1e6], [1.001], [1e6])
    off = cm.Book([130.0], [1e6], [131.0], [1e6])
    kes = cm.Mids(send_local=165.0, send_usd=1.27, usd_local=129.9)
    for asset, to_stable in (("USDC", True), ("XRP", False)):
        res = cm.simulate(200, asset, on, off, kes, cm.RouteFees(swap_pct=0.1), swap=swap, swap_to_stable=to_stable)
        assert res.cost_pct == pytest.approx(100 * (1 - res.received / (200 * 165.0)))


def test_thin_books_and_fees_larger_than_amount_raise():
    thin = cm.Book([1.0], [1], [1.0], [1])
    with pytest.raises(ValueError, match="on-ramp"):
        cm.simulate(200, "USDT", thin, cm.Book.flat(100), GBP_INR, cm.RouteFees())
    with pytest.raises(ValueError, match="off-ramp"):
        cm.simulate(200, "USDT", cm.Book.flat(0.79), thin, GBP_INR, cm.RouteFees())
    with pytest.raises(ValueError, match="swap"):
        cm.simulate(200, "USDC", cm.Book.flat(0.79), cm.Book.flat(100), GBP_INR, cm.RouteFees(), swap=thin)
    with pytest.raises(ValueError, match="nothing left"):
        cm.simulate(200, "USDT", cm.Book.flat(0.79), cm.Book.flat(100), GBP_INR,
                    cm.RouteFees(deposit_fixed=150, withdraw_fixed_send=60))


def test_missing_fx_rate_raises():
    c = Corridor("GBR", "IND", "India", "GBP", "INR")
    with pytest.raises(KeyError):
        cm.mids_for(c, {("GBP", "INR"): 127.0})  # no GBP->USD


# ---------------------------------------------------------------- properties

pct = st.floats(min_value=0, max_value=5)
fixed_send = st.floats(min_value=0, max_value=20)
spread = st.floats(min_value=0, max_value=0.02)


def _books(half_spread_on, half_spread_off):
    on_mid, off_mid = 1 / 1.27, 100.0
    on = cm.Book([on_mid * (1 - half_spread_on)], [1e9], [on_mid * (1 + half_spread_on)], [1e9])
    off = cm.Book([off_mid * (1 - half_spread_off)], [1e9], [off_mid * (1 + half_spread_off)], [1e9])
    return on, off


@settings(max_examples=200, deadline=None)
@given(pct, pct, fixed_send, fixed_send, st.floats(0, 3), st.floats(0, 500), spread, spread)
def test_cost_is_never_negative_without_a_premium(on_pct, off_pct, dep, wsend, wasset, payout, s_on, s_off):
    fees = cm.RouteFees(deposit_fixed=dep, onramp_pct=on_pct, withdraw_fixed_send=wsend,
                        withdraw_fixed_asset=wasset, offramp_pct=off_pct, payout_fixed_local=payout)
    on, off = _books(s_on, s_off)
    res = cm.simulate(200, "USDT", on, off, GBP_INR, fees)
    assert res.cost_pct >= -1e-9
    assert sum(res.contributions().values()) == pytest.approx(res.cost_pct, abs=1e-9)


FIELDS = ["deposit_fixed", "onramp_pct", "onramp_fx_pct", "withdraw_fixed_asset", "withdraw_fixed_send",
          "offramp_pct", "payout_fixed_local", "tax_pct"]


@settings(max_examples=200, deadline=None)
@given(st.sampled_from(FIELDS), st.floats(0, 2), st.floats(0.001, 2), spread, spread)
def test_total_cost_rises_with_any_fee(field, base, bump, s_on, s_off):
    on, off = _books(s_on, s_off)
    lo = cm.simulate(200, "USDT", on, off, GBP_INR, cm.RouteFees(**{field: base}))
    hi = cm.simulate(200, "USDT", on, off, GBP_INR, cm.RouteFees(**{field: base + bump}))
    assert hi.cost_pct > lo.cost_pct


@settings(max_examples=100, deadline=None)
@given(st.floats(0, 3), st.floats(0, 3), st.floats(0, 10), st.floats(0.5, 5))
def test_breakeven_amount_is_where_closed_form_cost_meets_target(on_pct, off_pct, fixed, target):
    a = cm.breakeven_amount(on_pct, off_pct, fixed, target)
    if math.isinf(a):
        assert cm.closed_form_cost(1e9, on_pct, off_pct, fixed) > target - 1e-6
    elif a > 0:
        assert cm.closed_form_cost(a, on_pct, off_pct, fixed) == pytest.approx(target, abs=1e-6)


def test_closed_form_rejects_non_positive_amount():
    with pytest.raises(ValueError):
        cm.closed_form_cost(0, 1, 1, 1)


# ---------------------------------------------------------------- routes and fees


def test_every_route_has_fees_and_a_withdrawal_fee():
    fees = fee_lookup(load_fees())
    rs = cm.routes()
    assert not [r for r in rs if r.corridor.dest == "PAK"]  # no measurable off-ramp in Pakistan
    for r in rs:
        ranges = cm.fee_ranges(r, fees)
        assert all(lo <= hi for lo, hi in ranges.values()), r.key
        assert ranges["withdraw_fixed_asset"] != (0.0, 0.0) or ranges["withdraw_fixed_send"] != (0.0, 0.0), r.key


def test_fee_ranges_unit_handling():
    fees = fee_lookup(load_fees())
    gbp_ind = Corridor("GBR", "IND", "India", "GBP", "INR")
    rev = cm.Route(gbp_ind, "USDT", "revolut", None, "coindcx", "coindcx:I-USDT_INR", tax="india_tax")
    r = cm.fee_ranges(rev, fees)
    assert r["withdraw_fixed_send"][0] >= 3 and r["withdraw_fixed_asset"] == (0.0, 0.0)
    assert r["tax_pct"] == (1.0, 1.0)
    bad = cm.Route(gbp_ind, "XRP", "coinbase", None, "coindcx", "coindcx:I-XRP_INR")
    with pytest.raises(KeyError):
        cm.fee_ranges(bad, fees)


def test_draw_fees_midpoint_and_tax_switch():
    ranges = {f: (0.0, 2.0) for f in FIELDS} | {"swap_pct": (0.0, 0.0)}
    mid = cm.draw_fees(ranges, None)
    assert mid.onramp_pct == 1.0 and mid.tax_pct == 1.0
    assert cm.draw_fees(ranges, None, include_tax=False).tax_pct == 0.0
    d = cm.draw_fees(ranges, np.random.default_rng(1))
    assert 0 <= d.offramp_pct <= 2


def _snapshot_frames():
    ts = pd.Timestamp("2026-10-26 02:20:16", tz="UTC")
    books = pd.DataFrame([
        {"ts": ts, "venue": "kraken", "symbol": "USDTGBP", "mid": 0.7465, "bid_px": [0.746], "bid_qty": [1e6],
         "ask_px": [0.747], "ask_qty": [1e6]},
        {"ts": ts, "venue": "coindcx", "symbol": "I-USDT_INR", "mid": 100.75, "bid_px": [100.74], "bid_qty": [1e6],
         "ask_px": [100.76], "ask_qty": [1e6]},
        {"ts": ts, "venue": "coindcx", "symbol": "I-XRP_INR", "mid": np.nan, "bid_px": [], "bid_qty": [],
         "ask_px": [], "ask_qty": []},
    ])
    wise = pd.DataFrame([{"pulled_at": ts + pd.Timedelta(seconds=40), "provider_alias": "wise", "is_mid": True,
                          "send_amount": 200.0, "send_ccy": s, "recv_ccy": r, "rate": v}
                         for s, r, v in (("GBP", "INR", 127.2), ("GBP", "USD", 1.3385), ("USD", "INR", 95.05))])
    return books, wise


def test_snapshot_rounds_and_monte_carlo():
    books, wise = _snapshot_frames()
    rounds = cm.snapshot_rounds(books, wise)
    assert len(rounds) == 1
    rnd = next(iter(rounds.values()))
    assert "coindcx:I-XRP_INR" not in rnd["books"]  # empty book dropped, counted as an outage
    c = Corridor("GBR", "IND", "India", "GBP", "INR")
    route = cm.Route(c, "USDT", "kraken", "kraken:USDTGBP", "coindcx", "coindcx:I-USDT_INR", tax="india_tax")
    fees = fee_lookup(load_fees())
    draws = cm.monte_carlo(route, rounds, fees, 200, n=200)
    assert len(draws) == 200 and draws.attrs["rounds_used"] == 1
    assert (draws.cost_ex_premium > draws.cost_pct).all()  # India's USDT premium lowers the cost
    s = cm.summarise(route, draws, {"B1": 0.15, "B2": 1.5})
    assert s["cost_p05"] <= s["cost_p50"] <= s["cost_p95"]
    # the share can be negative when USDT trades below the official rate on the UK side
    assert 0 <= s["P_beats_B1"] <= 1 and np.isfinite(s["fx_share_p50"])
    xrp = cm.Route(c, "XRP", "kraken", "kraken:XRPGBP", "coindcx", "coindcx:I-XRP_INR")
    assert cm.monte_carlo(xrp, rounds, fees, 200, n=10).empty
