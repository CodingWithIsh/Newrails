"""End to end: the committed cache reproduces every results table and chart (offline)."""

import json

import pandas as pd
import pytest

from plumbing import cli, net, plots, report


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("results")
    return report.build(out=out, n_draws=100), out


def test_report_writes_every_table(built):
    res, out = built
    for name in ("summary", "costs", "best", "rpw_bench", "wise_bench", "hypotheses", "xrp_var", "peg_bands",
                 "network_fee_tails", "speed_onchain", "amount_curve"):
        assert (out / f"{name}.csv").exists(), name
    s = pd.read_csv(out / "summary.csv")
    assert {"section", "corridor", "rail", "metric", "estimate", "low", "high", "unit", "method", "n"} <= set(s.columns)
    assert set(s["section"]) >= {"cost", "benchmark", "speed", "risk", "fees"}
    assert res["hypotheses"]["id"].tolist() == ["H1", "H2", "H3", "H4", "H5", "H6"]
    assert not res["costs"]["corridor"].str.contains("PAK").any()  # no measurable off-ramp


def test_summary_ranges_bracket_estimates(built):
    s = built[0]["summary"]
    ranged = s[s["metric"].str.startswith(("all-in cost", "cost excluding"))]
    assert (ranged["low"] <= ranged["estimate"]).all() and (ranged["estimate"] <= ranged["high"]).all()


def test_rpw_benchmark_regression_inside_report(built):
    b = built[0]["rpw_bench"].set_index("corridor")
    assert (b.loc[b.index.str.startswith("GBR"), "B1"] <= b.loc[b.index.str.startswith("GBR"), "B2"]).all()


def test_all_charts_render(built, tmp_path):
    paths = plots.make_all(built[0], tmp_path)
    assert len(paths) == 8
    assert all(p.stat().st_size > 20_000 for p in paths)


# ---------------------------------------------------------------- net helpers


class FakeResponse:
    def __init__(self, payload):
        self.payload, self.content, self.text = payload, json.dumps(payload).encode(), json.dumps(payload)

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append(("GET", url, params))
        return FakeResponse({"ok": True})

    def post(self, url, json=None, timeout=None):
        self.calls.append(("POST", url, json))
        return FakeResponse({"echo": json})


def test_client_paces_and_round_trips(monkeypatch):
    waits = []
    monkeypatch.setattr(net.time, "sleep", waits.append)
    c = net.Client(session=FakeSession(), pacing={"example.com": 10.0})
    assert c.get_json("https://example.com/a") == {"ok": True}
    assert c.post_json("https://example.com/b", {"x": 1}) == {"echo": {"x": 1}}
    assert waits and waits[0] > 9  # second call to the same host waited
    assert net.make_session().headers["User-Agent"].startswith("numbers-behind-the-money")


def test_raw_cache_round_trip_and_manifest(tmp_path):
    env = net.envelope("src", "https://example.com", {"a": 1}, {"p": 2})
    path = net.save_json(tmp_path / "x" / "a.json.gz", env)
    assert net.load_json(path)["payload"] == {"a": 1}
    (tmp_path / "plain.json").write_text('{"b": 2}')
    assert net.load_json(tmp_path / "plain.json") == {"b": 2}
    net.append_jsonl(tmp_path / "s.jsonl", {"n": 1})
    (tmp_path / "s.jsonl").open("a").write('{"torn"\n\n')
    assert list(net.iter_jsonl(tmp_path / "s.jsonl")) == [{"n": 1}]
    m = pd.read_csv(net.write_manifest(tmp_path))
    assert set(m["path"]) == {"x/a.json.gz", "plain.json", "s.jsonl"}
    assert m["sha256"].str.len().eq(64).all()
    assert len(net.stamp()) == 16


# ---------------------------------------------------------------- command line


def test_cli_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "run", lambda **kw: calls.append(("run", kw)))
    monkeypatch.setattr(cli, "live", lambda minutes: calls.append(("live", minutes)))
    import plumbing.ingest_ramps as ramps
    monkeypatch.setattr(ramps, "collect", lambda hours, every_min: calls.append(("collect", hours, every_min)))
    assert cli.main(["run", "--all", "--draws", "10"]) == 0
    assert cli.main(["live", "--minutes", "1"]) == 0
    assert cli.main(["collect", "--hours", "0.1"]) == 0
    assert calls == [("run", {"refresh": False, "draws": 10, "manifest": True}), ("live", 1.0), ("collect", 0.1, 10.0)]
    with pytest.raises(SystemExit):
        cli.main([])


def test_cli_run_offline_uses_cache(monkeypatch, tmp_path):
    import plumbing.config as config
    seen = {}
    monkeypatch.setattr(config, "RAW", tmp_path)  # no raw snapshots: a fresh clone
    monkeypatch.setattr(report, "build", lambda n_draws: seen.setdefault("res", {"hypotheses": pd.DataFrame(
        {"id": ["H1"], "held": [True], "result": ["x"]})}))
    monkeypatch.setattr(plots, "make_all", lambda res: [tmp_path / "f.png"])
    cli.run(refresh=False, draws=5)
    assert "res" in seen
