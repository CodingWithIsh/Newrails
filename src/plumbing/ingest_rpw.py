"""World Bank Remittance Prices Worldwide (RPW): load, clean, interpolate to £200, benchmark.

Cleaning follows project 1 (github.com/CodingWithIsh/numbers-behind-the-money, rpw.py) and the
World Bank's method: total cost = fee / amount + exchange-rate margin, simple averages across
services, and services that do not disclose their rate ("transparent" = no) excluded.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from plumbing import schemas
from plumbing.config import CACHE, RAW, RPW_PERIOD, Corridor

XLSX = RAW / "rpw" / "rpw_dataset_2011_2025_q3.xlsx"
URL = "https://datacatalogfiles.worldbank.org/ddh-published/0037898/DR0095523/rpw_dataset_2011_2025_q3.xlsx"
SHEET = "Dataset (from Q2 2016)"
CACHE_FILE = CACHE / "rpw_q3_2025.parquet"

RENAME = {
    "payment instrument": "payment_instrument",
    "access point": "access_point",
    "speed actual": "speed",
    "pickup method": "pickup_method",
    "cc1 lcu amount": "amount_1", "cc1 lcu fee": "fee_1", "cc1 fx margin": "margin_1",
    "cc1 total cost %": "total_1", "cc1 lcu fx rate": "rate_1", "cc1 lcu code": "send_ccy",
    "cc2 lcu amount": "amount_2", "cc2 lcu fee": "fee_2", "cc2 fx margin": "margin_2",
    "cc2 total cost %": "total_2", "cc2 lcu fx rate": "rate_2",
    "inter lcu bank fx": "interbank_fx",
    "receiving network coverage": "network_coverage",
}
NUMERIC = ["amount_1", "fee_1", "margin_1", "total_1", "rate_1",
           "amount_2", "fee_2", "margin_2", "total_2", "rate_2", "interbank_fx"]
KEEP = ["id", "period", "date", "source_code", "source_name", "destination_code", "destination_name",
        "firm", "firm_type", "payment_instrument", "access_point", "speed", "pickup_method",
        "network_coverage", "transparent", "send_ccy", *NUMERIC]

ACCOUNT_PICKUPS = ("Bank account", "Own/partner Bank account", "Mobile wallet")
SPEED_ORDER = ["Less than one hour", "Same day", "Next day", "2 days", "3-5 days", "6 days or more"]
SPEED_HOURS = {  # upper bound of each RPW speed band, in hours, for summary statistics only
    "Less than one hour": 1, "Same day": 24, "Next day": 48, "2 days": 72, "3-5 days": 120, "6 days or more": np.inf,
}


def read_xlsx(path: Path = XLSX) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=SHEET, engine="openpyxl")
    return df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.rename(columns=RENAME).copy()
    df["transparent"] = df["transparent"].astype(str).str.strip().str.lower().eq("yes")
    for col in NUMERIC:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    df["id"] = pd.to_numeric(df["id"], errors="coerce").astype("int64")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["period", "source_code", "source_name", "destination_code", "destination_name", "firm",
                "firm_type", "payment_instrument", "access_point", "speed", "pickup_method",
                "network_coverage", "send_ccy"]:
        df[col] = df[col].astype("string").str.strip()
    df["destination_name"] = df["destination_name"].replace({"Gambia, The": "The Gambia"})
    return df[KEEP]


def build_cache(xlsx: Path = XLSX, out: Path = CACHE_FILE, periods: tuple[str, ...] = (RPW_PERIOD,)) -> Path:
    """Keep the survey rounds we use (all corridors, so the global average can be reproduced)."""
    df = clean(read_xlsx(xlsx))
    df = df[df["period"].isin(periods)].reset_index(drop=True)
    schemas.RPW.validate(df)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False, compression="zstd")
    return out


def load(path: Path = CACHE_FILE, transparent_only: bool = True) -> pd.DataFrame:
    df = pd.read_parquet(path)
    return df[df["transparent"]].reset_index(drop=True) if transparent_only else df


# ------------------------------------------------------------------ published averages


def global_average(df: pd.DataFrame, period: str = RPW_PERIOD) -> float:
    return float(df.loc[df["period"] == period, "total_1"].mean())


def country_average(df: pd.DataFrame, source_code: str, period: str = RPW_PERIOD) -> float:
    return float(df.loc[(df["period"] == period) & (df["source_code"] == source_code), "total_1"].mean())


# ------------------------------------------------------------------ interpolation to any amount


def interpolate(df: pd.DataFrame, amount: float) -> pd.DataFrame:
    """Cost of each service at `amount`, interpolating fee and margin between its two RPW quotes.

    Inside [amount_1, amount_2] this is linear interpolation of that service's own prices; outside it
    the nearer quote's fee and margin are held flat (no extrapolation) and the row is flagged.
    Where the second quote is missing, the first quote's fee and margin are used and flagged.
    """
    out = df.copy()
    a1, a2 = out["amount_1"], out["amount_2"]
    have2 = out["fee_2"].notna() & out["margin_2"].notna() & a2.notna() & (a2 > a1)
    w = ((amount - a1) / (a2 - a1)).where(have2, 0.0).clip(0.0, 1.0)
    out["fee"] = out["fee_1"] + (out["fee_2"].fillna(out["fee_1"]) - out["fee_1"]) * w
    out["margin"] = out["margin_1"] + (out["margin_2"].fillna(out["margin_1"]) - out["margin_1"]) * w
    out["amount"] = float(amount)
    out["fee_pct"] = out["fee"] / amount * 100
    out["total"] = out["fee_pct"] + out["margin"]
    inside = have2 & (amount >= a1) & (amount <= a2)
    out["interp"] = np.select([inside, have2], ["linear", "held_flat"], default="first_quote_only")
    return out


def check_total_identity(df: pd.DataFrame, tol: float = 0.02) -> float:
    """RPW's published total should equal fee/amount + margin; returns the share of rows that agree."""
    implied = df["fee_1"] / df["amount_1"] * 100 + df["margin_1"]
    ok = (implied - df["total_1"]).abs() <= tol
    return float(ok[df["total_1"].notna()].mean())


# ------------------------------------------------------------------ benchmarks


def corridor_quotes(df: pd.DataFrame, corridor: Corridor, period: str = RPW_PERIOD) -> pd.DataFrame:
    return df[(df["period"] == period) & (df["source_code"] == corridor.source)
              & (df["destination_name"] == corridor.dest_name)]


def is_digital_to_account(df: pd.DataFrame) -> pd.Series:
    """Sent online and delivered to a bank account or mobile wallet: the product a crypto rail mimics."""
    return df["access_point"].eq("Internet").fillna(False) & df["pickup_method"].isin(ACCOUNT_PICKUPS).fillna(False)


def benchmarks(df: pd.DataFrame, corridor: Corridor, amount: float, period: str = RPW_PERIOD) -> dict[str, float]:
    """B1 cheapest digital-to-account service with a margin >= 0; B2 its group median; B3 corridor mean."""
    q = interpolate(corridor_quotes(df, corridor, period), amount)
    digital = q[is_digital_to_account(q)]
    eligible = digital[digital["margin"] >= 0]
    b1 = eligible.loc[eligible["total"].idxmin()] if len(eligible) else None
    return {
        "corridor": corridor.key,
        "amount": float(amount),
        "n_services": len(q),
        "n_digital": len(digital),
        "B1": float(b1["total"]) if b1 is not None else np.nan,
        "B1_firm": str(b1["firm"]) if b1 is not None else "",
        "B1_margin": float(b1["margin"]) if b1 is not None else np.nan,
        "B1_fee_pct": float(b1["fee_pct"]) if b1 is not None else np.nan,
        "B2": float(digital["total"].median()) if len(digital) else np.nan,
        "B2_margin": float(digital["margin"].median()) if len(digital) else np.nan,
        "B3": float(q["total"].mean()) if len(q) else np.nan,
        "B3_margin": float(q["margin"].mean()) if len(q) else np.nan,
        "min_raw": float(q["total"].min()) if len(q) else np.nan,
        "share_margin_B3": float(q["margin"].mean() / q["total"].mean()) if len(q) else np.nan,
    }


def speed_distribution(df: pd.DataFrame, corridor: Corridor, period: str = RPW_PERIOD) -> pd.Series:
    q = corridor_quotes(df, corridor, period)
    return (q["speed"].value_counts(normalize=True).reindex(SPEED_ORDER).fillna(0.0)
            .rename(corridor.key))
