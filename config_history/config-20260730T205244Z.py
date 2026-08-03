"""League settings + scoring config. Snapshot to config_history/ before every change:
    python config.py --snapshot
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- ESPN league identity -------------------------------------------------
LEAGUE_ID: int | None = 1152031
YEAR: int = 2026

# --- League shape (defaults per DESIGN.md §13 — confirm and update) -------
NUM_TEAMS = 12

ROSTER_SLOTS = {
    "QB": 1,
    "RB": 2,
    "WR": 2,
    "TE": 1,
    "FLEX": 1,       # eligible: RB/WR/TE
    "K": 1,
    "DST": 1,
    "BENCH": 7,
    "IR": 1,
}

# Share of the FLEX slot each position is assumed to fill, for replacement-level math (§6.2).
# Tune once real roster behavior is observed; must sum to 1.0.
FLEX_SHARE = {
    "RB": 0.45,
    "WR": 0.45,
    "TE": 0.10,
}

# --- Scoring (confirmed 2026-07-30: full PPR, 6-pt passing TD) ---
SCORING = {
    "pass_yds": 0.04,
    "pass_td": 6,
    "pass_int": -2,
    "rush_yds": 0.10,
    "rush_td": 6,
    "rec": 1,             # PPR value: 0 = standard, 0.5 = half-PPR, 1 = full PPR
    "rec_yds": 0.10,
    "rec_td": 6,
    "fumbles_lost": -2,
    "two_pt": 2,
}

# Kicker / DST use their own scoring tables (ESPN-provided actuals; not derived from SCORING above).

# --- Tiering (§6.3) ---------------------------------------------------------
# New tier starts when the gap to the next player exceeds this multiple of the
# position's local average gap.
TIER_GAP_MULTIPLIER = 0.75

# --- Paths -------------------------------------------------------------------
ROOT = Path(__file__).parent
DB_PATH = ROOT / "fantasy.db"
DATA_DIR = ROOT / "data"
DOCS_DATA_DIR = ROOT / "docs" / "data"
CROSSWALK_CSV = DATA_DIR / "player-crosswalk.csv"
CROSSWALK_OVERRIDES = DATA_DIR / "crosswalk-overrides.json"
CONFIG_HISTORY_DIR = ROOT / "config_history"

# --- Credentials (imports clean without secrets — see DESIGN.md §7.7) --------
try:
    from espn_credentials import ESPN_SWID, ESPN_S2  # type: ignore
except ImportError:
    ESPN_SWID = ESPN_S2 = None


def snapshot() -> Path:
    """Copy this file into config_history/ with a UTC timestamp. Run before every config change."""
    CONFIG_HISTORY_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = CONFIG_HISTORY_DIR / f"config-{stamp}.py"
    shutil.copy(__file__, dest)
    return dest


if __name__ == "__main__":
    if "--snapshot" in sys.argv:
        print(f"Snapshotted config.py -> {snapshot()}")
    else:
        print("Usage: python config.py --snapshot")
