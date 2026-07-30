"""The football valuation brain (DESIGN.md §6): projected points -> VBD/VOR -> tiers -> ADP value.

STAT_MAP below is a best-guess mapping from espn_api's `breakdown` stat-abbrev keys to our
SCORING keys (config.py). VERIFY against a live payload once real league data is available —
DESIGN.md §9 flags this as an explicit unknown ("football stat abbrevs — inspect once and map").
"""
from __future__ import annotations

import pandas as pd

import config

STAT_MAP = {
    "passingYards": "pass_yds",
    "passingTouchdowns": "pass_td",
    "passingInterceptions": "pass_int",
    "rushingYards": "rush_yds",
    "rushingTouchdowns": "rush_td",
    "receivingReceptions": "rec",
    "receivingYards": "rec_yds",
    "receivingTouchdowns": "rec_td",
    "lostFumbles": "fumbles_lost",
    "passing2PtConversions": "two_pt",
    "rushing2PtConversions": "two_pt",
    "receiving2PtConversions": "two_pt",
}


def projected_points(row: pd.Series, scoring: dict = config.SCORING) -> float:
    total = 0.0
    for espn_stat, scoring_key in STAT_MAP.items():
        val = row.get(f"proj_{espn_stat}")
        if pd.notna(val):
            total += float(val) * scoring.get(scoring_key, 0)
    return round(total, 2)


def add_projected_points(view: pd.DataFrame) -> pd.DataFrame:
    view = view.copy()
    view["projected_points"] = view.apply(projected_points, axis=1)
    return view


def _replacement_rank(position: str) -> int:
    """N_pos = teams x (starters_at_pos + flex share of the FLEX slot(s)) — DESIGN.md §6.2."""
    teams = config.NUM_TEAMS
    starters = config.ROSTER_SLOTS.get(position, 0)
    flex_n = config.ROSTER_SLOTS.get("FLEX", 0) * config.FLEX_SHARE.get(position, 0)
    return max(1, round(teams * (starters + flex_n)))


def replacement_levels(view: pd.DataFrame) -> dict:
    levels = {}
    for position, group in view.groupby("position"):
        ranked = group.sort_values("projected_points", ascending=False).reset_index(drop=True)
        n = min(_replacement_rank(position), len(ranked)) - 1
        levels[position] = float(ranked.loc[n, "projected_points"]) if n >= 0 else 0.0
    return levels


def add_vbd(view: pd.DataFrame) -> pd.DataFrame:
    view = view.copy()
    levels = replacement_levels(view)
    view["replacement_points"] = view["position"].map(levels).fillna(0)
    view["vbd"] = (view["projected_points"] - view["replacement_points"]).round(2)
    return view


def add_tiers(view: pd.DataFrame, gap_multiplier: float = config.TIER_GAP_MULTIPLIER) -> pd.DataFrame:
    """Gap-based tiers within each position (DESIGN.md §6.3): new tier when the gap to the next
    player exceeds `gap_multiplier` x the running average gap seen so far at that position."""
    view = view.copy()
    view["tier"] = 0
    for position, group in view.groupby("position"):
        ranked = group.sort_values("vbd", ascending=False)
        idx = ranked.index.tolist()
        vbds = ranked["vbd"].tolist()
        tier = 1
        gaps_seen = []
        view.loc[idx[0], "tier"] = tier
        for i in range(1, len(vbds)):
            gap = vbds[i - 1] - vbds[i]
            avg_gap = sum(gaps_seen) / len(gaps_seen) if gaps_seen else max(gap, 0.5)
            if gap > gap_multiplier * avg_gap and gaps_seen:
                tier += 1
            gaps_seen.append(gap)
            view.loc[idx[i], "tier"] = tier
    return view


def add_adp_value(view: pd.DataFrame) -> pd.DataFrame:
    """vbd_rank (overall) vs ADP (overall). Positive gap = available later than his value = target;
    negative = going earlier than his value = reach/fade (DESIGN.md §6.4)."""
    view = view.copy()
    view["vbd_rank"] = view["vbd"].rank(ascending=False, method="min")
    view["adp_value"] = (view["adp"] - view["vbd_rank"]).round(1)
    return view


def evaluate(view: pd.DataFrame) -> pd.DataFrame:
    view = add_projected_points(view)
    view = add_vbd(view)
    view = add_tiers(view)
    view = add_adp_value(view)
    return view.sort_values("vbd", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    from pipeline.init_db import connect
    from pipeline.transform import player_season_view

    result = evaluate(player_season_view(connect()))
    print(result[["name", "position", "projected_points", "vbd", "tier", "adp_value"]].head(20))
