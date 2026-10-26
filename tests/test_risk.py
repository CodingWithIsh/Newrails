import numpy as np
import pandas as pd
import pytest
from scipy import stats

from plumbing import risk

RNG = np.random.default_rng(7)
SIGMA = 0.002  # per-minute log-return volatility of the synthetic series


def _gbm(n=200_000, sigma=SIGMA, seed=7):
    r = np.random.default_rng(seed).normal(0, sigma, n)
    return np.exp(np.concatenate([[0.0], np.cumsum(r)]))


def test_var_of_normal_returns_matches_closed_form():
    p = _gbm()
    for h in (1, 10):
        r = risk.horizon_returns(p, h)
        v, es = risk.var_es(r, 0.99)
        z = stats.norm.ppf(0.99)
        expected_var = 1 - np.exp(-z * SIGMA * np.sqrt(h))
        expected_es = 1 - np.exp(-SIGMA * np.sqrt(h) * stats.norm.pdf(z) / 0.01)  # approx for small sigma
        assert v == pytest.approx(expected_var, rel=0.05)
        assert es == pytest.approx(expected_es, rel=0.08)
        assert es > v


def test_horizon_returns_drop_gaps_and_validate():
    p = np.array([1.0, 1.1, np.nan, 1.2, 1.3])
    assert len(risk.horizon_returns(p, 1)) == 2
    with pytest.raises(ValueError):
        risk.horizon_returns(p, 0)
    with pytest.raises(ValueError):
        risk.var_es(np.array([]))


def test_bootstrap_interval_contains_point_estimate():
    r = risk.horizon_returns(_gbm(50_000), 10)
    v, _ = risk.var_es(r, 0.99)
    lo, hi = risk.block_bootstrap_var(r, 0.99, block=500, reps=100)
    assert lo <= v <= hi and hi - lo < v


def test_kupiec_known_values():
    lr, p = risk.kupiec(10, 1000, 0.99)  # exactly the expected number of exceedances
    assert lr == pytest.approx(0.0, abs=1e-9) and p == pytest.approx(1.0)
    lr, p = risk.kupiec(30, 1000, 0.99)  # three times too many
    assert p < 0.001
    assert risk.kupiec(0, 100, 0.99)[0] > 0
    with pytest.raises(ValueError):
        risk.kupiec(5, 0, 0.99)


def test_backtest_on_iid_returns_is_not_rejected():
    p = pd.Series(_gbm(60 * 1440, seed=11))
    bt = risk.backtest(p, h=10, level=0.99, window_days=5)
    assert bt["tests"] > 500
    assert bt["kupiec_p"] > 0.01


def test_var_table_square_root_of_time_for_iid_returns():
    p = pd.Series(_gbm(100_000))
    ts = pd.Series(pd.date_range("2021-01-01", periods=len(p), freq="min", tz="UTC"))
    t = risk.var_table(p, ts, [1, 10], [0.99], bootstrap_reps=20)
    assert t.loc[t.horizon_min == 10, "sqrt_time_ratio"].iloc[0] == pytest.approx(1.0, rel=0.1)
    assert np.allclose(t.var_gbp, 200 * t.var_pct / 100)


def test_var_by_year_and_regime():
    n = 3 * 1440 * 4
    calm = RNG.normal(0, 0.001, n // 2)
    stormy = RNG.normal(0, 0.004, n // 2)
    p = pd.Series(np.exp(np.concatenate([[0.0], np.cumsum(np.concatenate([calm, stormy]))])))
    ts = pd.Series(pd.date_range("2025-12-25", periods=len(p), freq="min", tz="UTC"))
    by_year = risk.var_by_group(p, ts, 10, 0.99, "year")
    assert set(by_year["year"]) == {2025, 2026}
    reg = risk.var_by_group(p, ts, 10, 0.99, "vol_regime")
    v = reg.set_index("vol_regime")["var_pct"]
    assert v["Q5 stormy"] > 3 * v["Q1 calm"]  # the regime is visible before the transfer starts
    with pytest.raises(ValueError):
        risk.var_by_group(p, ts, 10, 0.99, "weekday")


def test_prob_drift_exceeds():
    r = np.log(np.array([0.99, 0.995, 1.0, 1.01]))
    assert risk.prob_drift_exceeds(r, 0.6) == 0.25


def test_peg_bands_and_episode_recovery():
    ts = pd.date_range("2023-03-10", periods=6, freq="h", tz="UTC")
    hourly = pd.DataFrame({"pair": "usdcusd", "ts": ts, "close": [1.0, 0.9995, 0.994, 0.87, 0.97, 1.0]})
    b = risk.peg_bands(hourly)
    assert b.loc[0, "share_beyond_10bp"] == pytest.approx(3 / 6)
    assert b.loc[0, "share_beyond_100bp"] == pytest.approx(2 / 6)
    assert b.loc[0, "worst_close"] == 0.87
    m = hourly.assign(episode_start=ts[0])
    rec = risk.episode_recovery(m)
    assert rec.loc[0, "minutes_beyond"] == 3 and rec.loc[0, "hours_first_to_last"] == 2.0


def test_fee_conversion_and_tails():
    fees = pd.DataFrame({"time": pd.to_datetime(["2025-09-01 10:00", "2025-09-02 11:00"], utc=True),
                         "fee_native": [10.0, 20.0]})
    native = pd.DataFrame({"symbol": "TRXUSDT", "ts": pd.to_datetime(["2025-09-01", "2025-09-02"], utc=True),
                           "close": [0.3, 0.4]})
    fx = pd.DataFrame({"date": pd.to_datetime(["2025-09-01"]), "rate": [1.25]})
    gbp = risk.to_gbp(fees, native, fx, "TRXUSDT")
    assert gbp.tolist() == pytest.approx([10 * 0.3 / 1.25, 20 * 0.4 / 1.25])
    t = risk.fee_tails(gbp)
    assert t.loc[0, "max"] == pytest.approx(6.4) and t.loc[0, "n"] == 2
    by = risk.fee_tails(gbp, pd.Series(["a", "b"]))
    assert list(by.index) == ["a", "b"]
