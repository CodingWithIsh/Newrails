"""Settings fixed before any result was computed (see PLAN.md, section 4).

Changing a window or threshold here changes the analysis, so every change is a commit with a reason.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
CACHE = DATA / "cache"
MANUAL = DATA / "manual"
RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"

SEED = 20261026
USER_AGENT = "numbers-behind-the-money/0.1 (research; +https://github.com/CodingWithIsh)"

# Amounts
SEND_GBP = 200.0
SEND_USD = 200.0
RPW_AMOUNTS_GBP = (120.0, 300.0)  # RPW's UK equivalents of $200 and $500 (cc1, cc2)
RPW_AMOUNTS_USD = (200.0, 500.0)
AMOUNT_GRID = (50.0, 100.0, 120.0, 200.0, 300.0, 500.0, 1000.0)

# Windows (inclusive)
PRICE_WINDOW = (date(2021, 1, 1), date(2026, 9, 30))
FEE_WINDOW = (date(2024, 10, 1), date(2026, 9, 30))
RPW_PERIOD = "2025_3Q"

# Risk
VAR_HORIZONS_MIN = (1, 5, 10, 30, 60)
HEADLINE_HORIZON_MIN = 10
VAR_LEVELS = (0.95, 0.99)
PEG_EPISODE_THRESHOLD = 0.005  # hourly |price - 1| that opens a stress episode
PEG_BANDS_BPS = (10, 50, 100)

# Solana switched from TowerBFT to Alpenglow at this slot (about 21 Oct 2026). Never pool across it.
SOLANA_ALPENGLOW_SLOT = 459_653_000


@dataclass(frozen=True)
class Corridor:
    source: str  # ISO3 code of the sending country, as in RPW `source_code`
    dest: str  # ISO3 code of the receiving country
    dest_name: str  # RPW `destination_name`
    send_ccy: str
    recv_ccy: str

    @property
    def key(self) -> str:
        return f"{self.source}-{self.dest}"


CORRIDORS_GBP = (
    Corridor("GBR", "IND", "India", "GBP", "INR"),
    Corridor("GBR", "NGA", "Nigeria", "GBP", "NGN"),
    Corridor("GBR", "PHL", "Philippines", "GBP", "PHP"),
    Corridor("GBR", "PAK", "Pakistan", "GBP", "PKR"),
    Corridor("GBR", "KEN", "Kenya", "GBP", "KES"),
)
CORRIDORS_USD = (
    Corridor("USA", "IND", "India", "USD", "INR"),
    Corridor("USA", "NGA", "Nigeria", "USD", "NGN"),
    Corridor("USA", "PHL", "Philippines", "USD", "PHP"),
    Corridor("USA", "PAK", "Pakistan", "USD", "PKR"),
    Corridor("USA", "KEN", "Kenya", "USD", "KES"),
    Corridor("USA", "MEX", "Mexico", "USD", "MXN"),
)
CORRIDORS = CORRIDORS_GBP + CORRIDORS_USD
