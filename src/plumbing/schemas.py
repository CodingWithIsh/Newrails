"""Schemas for every dataset the analysis reads.

Tabular datasets are checked with `FrameSchema` (column types, ranges, unique keys); hand-entered
records (fee schedules, the availability matrix) are pydantic models, so a typo fails loudly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator, model_validator


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class Col:
    kind: Literal["float", "int", "str", "bool", "datetime", "object"]
    nullable: bool = False
    min: float | None = None
    max: float | None = None


@dataclass(frozen=True)
class FrameSchema:
    name: str
    columns: dict[str, Col]
    key: tuple[str, ...] = ()
    min_rows: int = 1
    extra_ok: bool = True
    notes: dict[str, str] = field(default_factory=dict)

    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        errors = []
        if len(df) < self.min_rows:
            errors.append(f"{len(df)} rows < {self.min_rows}")
        missing = set(self.columns) - set(df.columns)
        if missing:
            errors.append(f"missing columns {sorted(missing)}")
        if not self.extra_ok and (extra := set(df.columns) - set(self.columns)):
            errors.append(f"unexpected columns {sorted(extra)}")
        for name, col in self.columns.items():
            if name not in df.columns:
                continue
            s = df[name]
            if not col.nullable and s.isna().any():
                errors.append(f"{name}: {int(s.isna().sum())} nulls")
            ok = {
                "float": pd.api.types.is_float_dtype,
                "int": pd.api.types.is_integer_dtype,
                "str": lambda x: pd.api.types.is_string_dtype(x) or pd.api.types.is_object_dtype(x),
                "bool": pd.api.types.is_bool_dtype,
                "datetime": pd.api.types.is_datetime64_any_dtype,
                "object": lambda x: True,
            }[col.kind](s)
            if not ok:
                errors.append(f"{name}: dtype {s.dtype} is not {col.kind}")
                continue
            if col.min is not None and (s.dropna() < col.min).any():
                errors.append(f"{name}: values below {col.min}")
            if col.max is not None and (s.dropna() > col.max).any():
                errors.append(f"{name}: values above {col.max}")
        if self.key and set(self.key) <= set(df.columns) and df.duplicated(list(self.key)).any():
            errors.append(f"duplicate keys on {self.key}: {int(df.duplicated(list(self.key)).sum())}")
        if errors:
            raise SchemaError(f"{self.name}: " + "; ".join(errors))
        return df


# ------------------------------------------------------------------ tabular schemas

RPW = FrameSchema(
    "rpw",
    {
        "id": Col("int"), "period": Col("str"), "source_code": Col("str"), "destination_code": Col("str"),
        "destination_name": Col("str"), "firm": Col("str"), "firm_type": Col("str"),
        "access_point": Col("str", nullable=True), "pickup_method": Col("str", nullable=True),
        "speed": Col("str", nullable=True), "transparent": Col("bool"),
        "amount_1": Col("float", min=0), "fee_1": Col("float", nullable=True, min=0),
        "margin_1": Col("float", nullable=True, min=-30, max=70), "total_1": Col("float", nullable=True, min=-30, max=400),
        "amount_2": Col("float", nullable=True, min=0), "fee_2": Col("float", nullable=True, min=0),
        "margin_2": Col("float", nullable=True, min=-30, max=70), "total_2": Col("float", nullable=True, min=-30, max=400),
    },
    key=("id",),
    min_rows=1000,
    # Bounds are wide on purpose: RPW keeps genuine extremes that the published global average
    # includes, e.g. Türkiye -> Bulgaria fees larger than the amount sent (total 307%) and
    # South Africa -> Malawi margins near 59% where official and market rates diverge.
)

RAMP_BOOKS = FrameSchema(
    "ramp_books",
    {
        "ts": Col("datetime"), "venue": Col("str"), "symbol": Col("str"), "base": Col("str"), "quote": Col("str"),
        "role": Col("str"), "best_bid": Col("float", min=0), "best_ask": Col("float", min=0),
        "mid": Col("float", min=0), "spread_bps": Col("float", nullable=True), "crossed": Col("bool"),
        "bid_px": Col("object"), "bid_qty": Col("object"), "ask_px": Col("object"), "ask_qty": Col("object"),
    },
    key=("ts", "venue", "symbol"),
)

WISE_QUOTES = FrameSchema(
    "wise_quotes",
    {
        "pulled_at": Col("datetime"), "send_ccy": Col("str"), "recv_ccy": Col("str"),
        "send_amount": Col("float", min=0), "provider": Col("str"), "fee": Col("float", nullable=True, min=0),
        "rate": Col("float", min=0), "received": Col("float", nullable=True, min=0),
        "markup_pct": Col("float", nullable=True), "is_mid": Col("bool"),
    },
)

CANDLES = FrameSchema(
    "candles",
    {"ts": Col("datetime"), "open": Col("float", min=0), "high": Col("float", min=0),
     "low": Col("float", min=0), "close": Col("float", min=0), "volume": Col("float", min=0)},
    key=("ts",),
)

FX_DAILY = FrameSchema(
    "fx_daily",
    {"date": Col("datetime"), "base": Col("str"), "quote": Col("str"), "rate": Col("float", min=0), "source": Col("str")},
    key=("date", "base", "quote", "source"),
)

XRPL_LEDGERS = FrameSchema(
    "xrpl_ledgers",
    {"ledger_index": Col("int", min=32570), "close_time": Col("datetime"), "close_time_resolution": Col("int", min=1),
     "n_tx": Col("int", min=0)},
    key=("ledger_index",),
)

CHAIN_FEES = FrameSchema(
    "chain_fees",
    {"chain": Col("str"), "block": Col("int", min=0), "time": Col("datetime"), "tx_kind": Col("str"),
     "fee_native": Col("float", min=0)},
)


# ------------------------------------------------------------------ hand-entered records


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: HttpUrl
    accessed: date
    note: str | None = None


class FeeEntry(BaseModel):
    """One fee from a published schedule, as a range because most fees vary by tier or method."""

    model_config = ConfigDict(extra="forbid")
    provider: str
    leg: Literal["deposit", "trade", "spread", "withdraw_crypto", "withdraw_fiat", "convert", "payout"]
    asset: str  # currency or asset the fee applies to (GBP, USD, INR, XRP, USDT, ...)
    network: str | None = None  # for crypto withdrawals: XRPL, TRON, SOLANA
    kind: Literal["pct", "fixed"]
    low: float
    high: float
    unit: str  # "%" for pct, else the currency or asset of the fixed amount
    sources: list[Source]
    verified: bool = True  # False when only a secondary source could be found

    @field_validator("low", "high")
    @classmethod
    def non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("fees cannot be negative")
        return v

    @model_validator(mode="after")
    def ordered(self) -> FeeEntry:
        if self.high < self.low:
            raise ValueError(f"{self.provider} {self.leg}: high < low")
        if self.kind == "pct" and self.unit != "%":
            raise ValueError("percentage fees must use unit '%'")
        if self.leg == "withdraw_crypto" and not self.network:
            raise ValueError("crypto withdrawals need a network")
        return self


class Availability(BaseModel):
    """Whether one leg of a route exists: e.g. 'Kraken supports USDT withdrawals on Tron'."""

    model_config = ConfigDict(extra="forbid")
    venue: str
    asset: str
    network: str | None = None
    direction: Literal["buy_with_fiat", "sell_for_fiat", "deposit", "withdraw", "fiat_payout"]
    fiat: str | None = None
    status: Literal["yes", "no", "unverified"]
    sources: list[Source] = []
    note: str | None = None
