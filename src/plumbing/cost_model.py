"""All-in cost of a transfer on each rail, split the same way RPW splits it.

A crypto route is a chain of legs. Each leg multiplies the money in flight by a factor <= 1
(a fee or a spread) or by a factor that can be above 1 (a market's price against the official rate):

    received / (amount x official rate) = product of leg factors
    cost % = 100 x (1 - product)

Every leg has a category:
- "fee":     deposit, trading, withdrawal and payout fees
- "spread":  buying at the ask and selling at the bid, walked through the real order book
- "fx":      a venue's mid-market price against the official rate on the sending side
             (e.g. USDT/GBP on Kraken against official GBP/USD) and triangulation residuals
- "premium": the destination market's price against the official rate (e.g. USDT/INR against USD/INR)
- "tax":     India's 1% TDS, reported separately

"Exchange-rate cost" = spread + fx, which is what RPW's FX margin measures for a bank or money
transfer operator. The premium is kept apart because it reflects capital controls and tax, not the rail.

Legs are combined in logs, so each leg's share of the total is exact and does not depend on order.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from plumbing.config import CORRIDORS_GBP, CORRIDORS_USD, SEED, Corridor
from plumbing.schemas import FeeEntry

CATEGORIES = ("fee", "spread", "fx", "premium", "tax")
EXCHANGE_RATE = ("spread", "fx")
NETWORK = {"XRP": "XRPL", "USDT": "TRON", "USDC": "SOLANA"}


# ------------------------------------------------------------------ order books


def walk_asks(px: Sequence[float], qty: Sequence[float], quote_amount: float) -> float:
    """Base units bought by spending `quote_amount` against the asks (best first). NaN if the book is too thin."""
    if quote_amount < 0:
        raise ValueError("amount must be non-negative")
    remaining, got = quote_amount, 0.0
    for p, q in zip(px, qty, strict=True):
        cost = p * q
        if remaining <= cost:
            return got + remaining / p
        got += q
        remaining -= cost
    return float("nan") if remaining > 1e-12 else got


def walk_bids(px: Sequence[float], qty: Sequence[float], base_amount: float) -> float:
    """Quote currency received by selling `base_amount` into the bids (best first). NaN if too thin."""
    if base_amount < 0:
        raise ValueError("amount must be non-negative")
    remaining, proceeds = base_amount, 0.0
    for p, q in zip(px, qty, strict=True):
        take = min(q, remaining)
        proceeds += take * p
        remaining -= take
        if remaining <= 1e-12:
            return proceeds
    return float("nan") if remaining > 1e-12 else proceeds


@dataclass(frozen=True)
class Book:
    bid_px: Sequence[float]
    bid_qty: Sequence[float]
    ask_px: Sequence[float]
    ask_qty: Sequence[float]

    @property
    def mid(self) -> float:
        if not len(self.bid_px) or not len(self.ask_px):
            return float("nan")
        return (self.bid_px[0] + self.ask_px[0]) / 2

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Book:
        return cls(row["bid_px"], row["bid_qty"], row["ask_px"], row["ask_qty"])

    @classmethod
    def flat(cls, price: float, depth: float = 1e12) -> Book:
        """A synthetic book with no spread, for a provider that quotes one rate (e.g. 1:1 conversions)."""
        return cls([price], [depth], [price], [depth])


# ------------------------------------------------------------------ fees for one route


@dataclass(frozen=True)
class RouteFees:
    """Fee values for one evaluation (already drawn from their ranges). Percentages are in %."""

    deposit_fixed: float = 0.0  # in the sending currency
    onramp_pct: float = 0.0
    onramp_fx_pct: float = 0.0  # provider's own conversion margin where there is no public book
    withdraw_fixed_asset: float = 0.0  # charged in units of the asset
    withdraw_fixed_send: float = 0.0  # charged in the sending currency (e.g. Revolut's £1 / £3)
    swap_pct: float = 0.0
    offramp_pct: float = 0.0
    payout_fixed_local: float = 0.0
    tax_pct: float = 0.0


@dataclass(frozen=True)
class Mids:
    """Official mid-market rates at the moment of the snapshot."""

    send_local: float  # sending currency -> receiving currency
    send_usd: float  # sending currency -> USD (1.0 for a US sender)
    usd_local: float  # USD -> receiving currency


@dataclass
class Leg:
    name: str
    category: str
    factor: float


@dataclass
class Result:
    amount: float
    received: float
    official: float
    legs: list[Leg] = field(default_factory=list)

    @property
    def cost_pct(self) -> float:
        return 100 * (1 - self.received / self.official)

    def contributions(self) -> dict[str, float]:
        """Each category's share of cost %, allocated by log factor so the parts sum to the total."""
        logs = {c: 0.0 for c in CATEGORIES}
        for leg in self.legs:
            logs[leg.category] += -np.log(leg.factor)
        total_log = sum(logs.values())
        if abs(total_log) < 1e-15:
            return {c: 0.0 for c in CATEGORIES}
        return {c: self.cost_pct * v / total_log for c, v in logs.items()}

    def cost_excluding(self, *categories: str) -> float:
        keep = np.prod([leg.factor for leg in self.legs if leg.category not in categories])
        return 100 * (1 - keep)


def _fixed(name: str, before: float, fee: float, category: str = "fee") -> tuple[float, Leg]:
    after = before - fee
    if after <= 0:
        raise ValueError(f"{name}: nothing left after fixed fees")
    return after, Leg(name, category, after / before)


def simulate(amount: float, asset: str, on: Book, off: Book, mids: Mids, fees: RouteFees,
             swap: Book | None = None, swap_to_stable: bool = False) -> Result:
    """Follow `amount` (sending currency) through: deposit -> buy `asset` -> withdraw -> [swap] -> sell -> pay out.

    `on` is quoted in the sending currency, `off` in the receiving currency. If `swap` is given, the
    asset is first sold into it (quoted in USDT) and `off` is then a USDT book.
    """
    legs: list[Leg] = []
    x, leg = _fixed("deposit fee", amount, fees.deposit_fixed)
    legs.append(leg)
    x, leg = _fixed("withdrawal fee (charged in sending currency)", x, fees.withdraw_fixed_send)
    legs.append(leg)
    legs.append(Leg("on-ramp trading fee", "fee", 1 - fees.onramp_pct / 100))
    legs.append(Leg("on-ramp provider FX margin", "fx", 1 - fees.onramp_fx_pct / 100))
    x *= (1 - fees.onramp_pct / 100) * (1 - fees.onramp_fx_pct / 100)

    units = walk_asks(on.ask_px, on.ask_qty, x)
    if not np.isfinite(units) or units <= 0:
        raise ValueError("on-ramp book too thin")
    legs.append(Leg("on-ramp spread and depth", "spread", (units * on.mid) / x))

    units, leg = _fixed("withdrawal fee (charged in the asset)", units, fees.withdraw_fixed_asset)
    legs.append(leg)

    stable = asset in ("USDT", "USDC", "RLUSD")
    if stable:
        # venue price of the stablecoin against the official sending-currency -> USD rate
        legs.append(Leg("on-ramp venue vs official rate", "fx", (1 / mids.send_usd) / on.mid))

    if swap is not None:
        out = walk_bids(swap.bid_px, swap.bid_qty, units)
        if not np.isfinite(out):
            raise ValueError("swap book too thin")
        legs.append(Leg("swap spread", "spread", out / (units * swap.mid)))
        legs.append(Leg("swap fee", "fee", 1 - fees.swap_pct / 100))
        if swap_to_stable and stable:
            legs.append(Leg("swap venue vs $1", "fx", swap.mid))
        else:  # XRP -> USDT: the XRP price abroad against the UK price
            legs.append(Leg("XRP price abroad vs at home", "premium", swap.mid / (on.mid * mids.send_usd)))
        units = out * (1 - fees.swap_pct / 100)
        stable = True

    local = walk_bids(off.bid_px, off.bid_qty, units)
    if not np.isfinite(local) or local <= 0:
        raise ValueError("off-ramp book too thin")
    legs.append(Leg("off-ramp spread and depth", "spread", local / (units * off.mid)))

    if stable:
        legs.append(Leg("local market premium", "premium", off.mid / mids.usd_local))
        legs.append(Leg("official cross-rate residual", "fx", mids.send_usd * mids.usd_local / mids.send_local))
    else:  # XRP straight into local currency: XRP's price there against its UK price
        legs.append(Leg("XRP price abroad vs at home", "premium", off.mid / (on.mid * mids.send_local)))

    legs.append(Leg("off-ramp trading fee", "fee", 1 - fees.offramp_pct / 100))
    legs.append(Leg("tax withheld (TDS)", "tax", 1 - fees.tax_pct / 100))
    local *= (1 - fees.offramp_pct / 100) * (1 - fees.tax_pct / 100)
    local, leg = _fixed("payout fee", local, fees.payout_fixed_local)
    legs.append(leg)

    res = Result(amount=amount, received=local, official=amount * mids.send_local, legs=legs)
    check = np.prod([lg.factor for lg in legs])
    if not np.isclose(check, res.received / res.official, rtol=1e-9):
        raise AssertionError("leg factors do not reconcile with the amount received")
    return res


# ------------------------------------------------------------------ routes


@dataclass(frozen=True)
class Route:
    corridor: Corridor
    asset: str
    onramp: str  # fee provider, e.g. "kraken", "revolut"
    on_book: str | None  # "venue:symbol"; None for a provider without a public book
    offramp: str  # fee provider, e.g. "coindcx", "luno_ng"
    off_book: str
    swap_book: str | None = None
    tax: str | None = None
    proxy_note: str = ""

    @property
    def network(self) -> str:
        return NETWORK[self.asset]

    @property
    def rail(self) -> str:
        return {"XRP": "XRP (XRPL)", "USDT": "USDT (Tron)", "USDC": "USDC (Solana)"}[self.asset]

    @property
    def key(self) -> str:
        return f"{self.corridor.key}|{self.asset}|{self.onramp}->{self.offramp}"


OFFRAMPS: dict[str, list[tuple[str, str, str, str | None, str | None]]] = {
    # dest: (asset, offramp fee provider, off book, swap book, tax)
    "IND": [("XRP", "coindcx", "coindcx:I-XRP_INR", None, "india_tax"),
            ("USDT", "coindcx", "coindcx:I-USDT_INR", None, "india_tax"),
            ("USDC", "coindcx", "coindcx:I-USDC_INR", None, "india_tax")],
    "NGA": [("XRP", "luno_ng", "luno:XRPNGN", None, None),
            ("USDT", "luno_ng", "luno:USDTNGN", None, None),
            ("USDT", "quidax", "quidax:usdtngn", None, None),
            ("USDC", "luno_ng", "luno:USDTNGN", "luno:USDCUSDT", None)],
    "PHL": [("XRP", "coinsph", "coinsph:XRPPHP", None, None),
            ("USDT", "coinsph", "coinsph:USDTPHP", None, None),
            ("USDC", "coinsph", "coinsph:USDCPHP", None, None)],
    "KEN": [("XRP", "luno_ke", "luno:USDTKES", "luno:XRPUSDT", None),
            ("USDT", "luno_ke", "luno:USDTKES", None, None),
            ("USDC", "luno_ke", "luno:USDTKES", "luno:USDCUSDT", None)],
    "PAK": [],
    "MEX": [("XRP", "bitso", "bitso:xrp_mxn", None, None),
            ("USDT", "bitso", "bitso:usdt_mxn", None, None)],
}

ONRAMPS_GBP = {"XRP": [("kraken", "kraken:XRPGBP"), ("revolut", "kraken:XRPGBP")],
               "USDT": [("kraken", "kraken:USDTGBP"), ("coinbase", "coinbase:USDT-GBP"), ("revolut", None)],
               "USDC": [("kraken", "kraken:USDCGBP"), ("coinbase", "coinbase:USDC-GBP"), ("revolut", None)]}
ONRAMPS_USD = {"XRP": [("kraken", "kraken:XRPUSD")],
               "USDT": [("kraken", "kraken:USDTUSD"), ("coinbase", "coinbase:USDT-USD")],
               "USDC": [("kraken", "kraken:USDCUSD")]}


def routes(corridors: Iterable[Corridor] = CORRIDORS_GBP + CORRIDORS_USD) -> list[Route]:
    out = []
    for c in corridors:
        onramps = ONRAMPS_GBP if c.send_ccy == "GBP" else ONRAMPS_USD
        for asset, offramp, off_book, swap_book, tax in OFFRAMPS[c.dest]:
            for onramp, on_book in onramps[asset]:
                note = "Revolut's XRP price proxied by Kraken's XRP/GBP book" if onramp == "revolut" and asset == "XRP" else ""
                out.append(Route(c, asset, onramp, on_book, offramp, off_book, swap_book, tax, note))
    return out


# ------------------------------------------------------------------ fees: ranges to draws


def fee_ranges(route: Route, fees: Mapping[tuple[str, str, str, str | None], FeeEntry]) -> dict[str, tuple[float, float]]:
    """(low, high) for each RouteFees field; a missing entry is (0, 0) and listed in `missing`."""
    c = route.corridor

    def get(provider: str, leg: str, asset: str, network: str | None = None) -> tuple[float, float] | None:
        f = fees.get((provider, leg, asset, network))
        return (f.low, f.high) if f else None

    r: dict[str, tuple[float, float]] = {}
    r["deposit_fixed"] = get(route.onramp, "deposit", c.send_ccy) or (0.0, 0.0)
    r["onramp_pct"] = get(route.onramp, "trade", route.asset) or (0.0, 0.0)
    r["onramp_fx_pct"] = get(route.onramp, "spread", c.send_ccy) or (0.0, 0.0)
    w = fees.get((route.onramp, "withdraw_crypto", route.asset, route.network))
    if w is None:
        raise KeyError(f"no withdrawal fee for {route.onramp} {route.asset} on {route.network}")
    if w.unit == route.asset:
        r["withdraw_fixed_asset"], r["withdraw_fixed_send"] = (w.low, w.high), (0.0, 0.0)
    elif w.unit == c.send_ccy:
        r["withdraw_fixed_asset"], r["withdraw_fixed_send"] = (0.0, 0.0), (w.low, w.high)
    else:
        raise ValueError(f"withdrawal fee unit {w.unit} for a {c.send_ccy} sender")
    r["swap_pct"] = get(route.offramp, "trade", c.recv_ccy) if route.swap_book else (0.0, 0.0)
    r["offramp_pct"] = get(route.offramp, "trade", c.recv_ccy) or (0.0, 0.0)
    r["payout_fixed_local"] = get(route.offramp, "withdraw_fiat", c.recv_ccy) or (0.0, 0.0)
    r["tax_pct"] = get(route.tax, "payout", c.recv_ccy) if route.tax else (0.0, 0.0)
    return {k: (v if v is not None else (0.0, 0.0)) for k, v in r.items()}


def draw_fees(ranges: Mapping[str, tuple[float, float]], rng: np.random.Generator | None,
              include_tax: bool = True) -> RouteFees:
    """Uniform draw inside each published range (or the midpoint when rng is None)."""
    vals = {k: ((lo + hi) / 2 if rng is None else rng.uniform(lo, hi)) for k, (lo, hi) in ranges.items()}
    if not include_tax:
        vals["tax_pct"] = 0.0
    return RouteFees(**vals)


# ------------------------------------------------------------------ snapshots


def snapshot_rounds(books: pd.DataFrame, wise: pd.DataFrame) -> dict[pd.Timestamp, dict[str, Any]]:
    """Group book rows and Wise mid-market rates into the collector's 10-minute rounds."""
    b = books.dropna(subset=["mid"]).assign(round=lambda d: d["ts"].dt.floor("10min"))
    w = wise[(wise["provider_alias"] == "wise") & wise["is_mid"] & (wise["send_amount"] == 200)]
    w = w.assign(round=w["pulled_at"].dt.floor("10min"))
    rounds: dict[pd.Timestamp, dict[str, Any]] = {}
    for rnd, g in b.groupby("round"):
        rounds[rnd] = {"books": {f"{r.venue}:{r.symbol}": Book.from_row(r._asdict()) for r in g.itertuples()}}
    for rnd, g in w.groupby("round"):
        if rnd in rounds:
            rounds[rnd]["fx"] = {(r.send_ccy, r.recv_ccy): r.rate for r in g.itertuples()}
    return {k: v for k, v in rounds.items() if "fx" in v}


def mids_for(corridor: Corridor, fx: Mapping[tuple[str, str], float]) -> Mids:
    if corridor.send_ccy == "USD":
        return Mids(fx[("USD", corridor.recv_ccy)], 1.0, fx[("USD", corridor.recv_ccy)])
    return Mids(fx[("GBP", corridor.recv_ccy)], fx[("GBP", "USD")], fx[("USD", corridor.recv_ccy)])


def evaluate(route: Route, rnd: Mapping[str, Any], amount: float, fees: RouteFees) -> Result:
    books, fx = rnd["books"], rnd["fx"]
    mids = mids_for(route.corridor, fx)
    # Revolut has no public book: it converts at its own rate, modelled as official less its margin
    on = Book.flat(1 / mids.send_usd) if route.on_book is None else books[route.on_book]
    swap = books[route.swap_book] if route.swap_book else None
    return simulate(amount, route.asset, on, books[route.off_book], mids, fees, swap,
                    swap_to_stable=route.asset in ("USDC", "USDT"))


def monte_carlo(route: Route, rounds: Mapping[pd.Timestamp, Mapping[str, Any]],
                fees: Mapping[tuple[str, str, str, str | None], FeeEntry], amount: float,
                n: int = 2000, seed: int = SEED, include_tax: bool = True) -> pd.DataFrame:
    """Draw a snapshot (uniformly over collected rounds) and every fee (uniformly over its range).

    Rounds missing a needed book (an outage) are skipped and counted in `rounds_used`.
    """
    rng = np.random.default_rng(seed)
    ranges = fee_ranges(route, fees)
    needed = {route.on_book, route.off_book, route.swap_book} - {None}
    usable = [k for k, v in rounds.items() if needed <= set(v["books"])]
    rows = []
    if not usable:
        return pd.DataFrame()
    unfilled = 0
    for _ in range(n):
        rnd = rounds[usable[rng.integers(len(usable))]]
        try:
            res = evaluate(route, rnd, amount, draw_fees(ranges, rng, include_tax))
        except ValueError as exc:  # a book too thin for this amount: a liquidity result, not a bug
            if "too thin" not in str(exc):
                raise
            unfilled += 1
            continue
        con = res.contributions()
        rows.append({"cost_pct": res.cost_pct, "cost_ex_premium": res.cost_excluding("premium"),
                     "cost_ex_premium_tax": res.cost_excluding("premium", "tax"),
                     **{f"c_{k}": v for k, v in con.items()}})
    out = pd.DataFrame(rows)
    out.attrs["unfilled_share"] = unfilled / n
    out.attrs["rounds_used"] = len(usable)
    out.attrs["rounds_total"] = len(rounds)
    return out


def summarise(route: Route, draws: pd.DataFrame, bench: Mapping[str, float]) -> dict[str, Any]:
    """Point estimates and 5-95% ranges, the exchange-rate share, and P(beats each benchmark)."""
    q = draws.quantile([0.05, 0.5, 0.95])
    ex = draws["c_spread"] + draws["c_fx"]
    denom = draws["c_fee"] + ex
    share = (ex / denom).where(denom.abs() > 1e-9)
    return {
        "corridor": route.corridor.key, "rail": route.rail, "asset": route.asset, "onramp": route.onramp,
        "offramp": route.offramp, "route": route.key, "n_draws": len(draws),
        "rounds_used": draws.attrs.get("rounds_used"), "rounds_total": draws.attrs.get("rounds_total"),
        "unfilled_share": draws.attrs.get("unfilled_share", 0.0),
        **{f"cost_{k}": q.loc[p, "cost_pct"] for k, p in (("p05", 0.05), ("p50", 0.5), ("p95", 0.95))},
        **{f"ex_premium_{k}": q.loc[p, "cost_ex_premium_tax"] for k, p in (("p05", 0.05), ("p50", 0.5), ("p95", 0.95))},
        **{f"{c}_p50": draws[f"c_{c}"].median() for c in CATEGORIES},
        "fx_share_p50": float(share.median()),
        "P_beats_B1": float((draws["cost_pct"] < bench["B1"]).mean()),
        "P_beats_B2": float((draws["cost_pct"] < bench["B2"]).mean()),
        "P_beats_B1_ex_premium": float((draws["cost_ex_premium_tax"] < bench["B1"]).mean()),
        "P_beats_B2_ex_premium": float((draws["cost_ex_premium_tax"] < bench["B2"]).mean()),
        "note": route.proxy_note,
    }


# ------------------------------------------------------------------ closed-form breakeven


def closed_form_cost(amount: float, on_pct: float, off_pct: float, fixed: float) -> float:
    """Cost % when the on-ramp and off-ramp each cost a percentage and the route has `fixed` costs
    (in the sending currency): 1 - (1 - on)(1 - off)(1 - fixed / amount)."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    return 100 * (1 - (1 - on_pct / 100) * (1 - off_pct / 100) * (1 - fixed / amount))


def breakeven_amount(on_pct: float, off_pct: float, fixed: float, target_pct: float) -> float:
    """Smallest amount at which the route costs no more than `target_pct`; inf if never."""
    keep = (1 - on_pct / 100) * (1 - off_pct / 100)
    need = 1 - target_pct / 100
    if keep <= need:
        return float("inf")
    return fixed / (1 - need / keep)
