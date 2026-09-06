"""The football valuation brain (DESIGN.md §6): projected points -> VBD/VOR -> tiers -> ADP value.

STAT_MAP below is a best-guess mapping from espn_api's `breakdown` stat-abbrev keys to our
SCORING keys (config.py). VERIFY against a live payload once real league data is available —
DESIGN.md §9 flags this as an explicit unknown ("football stat abbrevs — inspect once and map").
"""
from __future__ import annotations

import statistics

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


def add_tiers(
    view: pd.DataFrame,
    gap_multiplier: float = config.TIER_GAP_MULTIPLIER,
    min_gap: float = config.TIER_MIN_GAP,
) -> pd.DataFrame:
    """Gap-based tiers within each position (DESIGN.md §6.3): a new tier starts when the VBD drop
    to the next player exceeds a threshold.

    The threshold is `gap_multiplier` x the *median* adjacent gap across the draftable top of the
    position (floored at `min_gap` points). Median, not mean: the huge gaps between the few elite
    players at a position would inflate a mean so far that no later break ever fires — the old
    running-mean version produced a single 15-deep RB "tier 1"."""
    view = view.copy()
    view["tier"] = 0
    for position, group in view.groupby("position"):
        ranked = group.sort_values("vbd", ascending=False)
        idx = ranked.index.tolist()
        vbds = ranked["vbd"].tolist()

        head = vbds[: min(len(vbds), 40)]
        pos_gaps = [head[i - 1] - head[i] for i in range(1, len(head)) if head[i - 1] - head[i] > 0]
        yardstick = statistics.median(pos_gaps) if pos_gaps else min_gap
        threshold = max(gap_multiplier * yardstick, min_gap)

        tier = 1
        view.loc[idx[0], "tier"] = tier
        for i in range(1, len(vbds)):
            if vbds[i - 1] - vbds[i] > threshold:
                tier += 1
            view.loc[idx[i], "tier"] = tier
    return view


def add_adp_value(view: pd.DataFrame) -> pd.DataFrame:
    """vbd_rank (overall) vs ADP (overall). Positive gap = available later than his value = target;
    negative = going earlier than his value = reach/fade (DESIGN.md §6.4)."""
    view = view.copy()
    view["vbd_rank"] = view["vbd"].rank(ascending=False, method="min")
    view["adp_value"] = (view["adp"] - view["vbd_rank"]).round(1)
    return view


def _risk_bucket(ecr: float, std: float) -> str | None:
    """Boom/bust from the spread of expert opinion. rank_std grows with ECR (deeper players are
    inherently more argued-over), so compare each player's std to what's typical at his ECR.
    `expected` is fit to the 2026 half-PPR board: median std ≈ 5 at ECR 12, ≈ 9 at 40, ≈ 16 at 90."""
    if pd.isna(ecr) or pd.isna(std):
        return None
    expected = 3.0 + 0.15 * float(ecr)
    ratio = float(std) / expected
    if ratio < 0.7:
        return "Safe"
    if ratio > 1.4:
        return "Volatile"
    return "Balanced"


def add_consensus(view: pd.DataFrame) -> pd.DataFrame:
    """Expert-consensus signals from FantasyPros ECR (added by transform when available):
      value_vs_ecr — ADP minus ECR; positive = the crowd lets him fall past where experts rank him
      risk         — Safe / Balanced / Volatile, from the expert-rank spread relative to his ECR
      ceiling      — True when the most bullish expert (rank_min) is well above consensus
    All are NaN/None when ECR wasn't matched for that player."""
    view = view.copy()
    if "ecr" not in view.columns:
        view["ecr"] = pd.NA
    for col in ("ecr_pos", "rank_min", "rank_max", "rank_std", "fp_tier"):
        if col not in view.columns:
            view[col] = pd.NA

    ecr = pd.to_numeric(view["ecr"], errors="coerce")
    std = pd.to_numeric(view["rank_std"], errors="coerce")
    rmin = pd.to_numeric(view["rank_min"], errors="coerce")
    adp = pd.to_numeric(view["adp"], errors="coerce")

    view["value_vs_ecr"] = (adp - ecr).round(1)
    view["risk"] = [_risk_bucket(e, s) for e, s in zip(ecr, std)]
    # ceiling: the most bullish expert has him clearly above consensus — >=30% higher, and by a
    # margin that scales with depth (so it stays meaningful past the early rounds).
    skill = view["position"].isin(["QB", "RB", "WR", "TE"])
    margin = (0.10 * ecr).clip(lower=5)
    view["ceiling"] = skill & (rmin <= 0.7 * ecr) & ((ecr - rmin) >= margin)
    view.loc[ecr.isna() | rmin.isna(), "ceiling"] = False
    return view


def evaluate(view: pd.DataFrame) -> pd.DataFrame:
    view = add_projected_points(view)
    view = add_vbd(view)
    view = add_tiers(view)
    view = add_adp_value(view)
    view = add_consensus(view)
    # Order the raw frame by expert consensus (ECR) where we have it, model VBD otherwise —
    # every dashboard page re-sorts, so this only affects how the JSON reads.
    view["_ecr_sort"] = pd.to_numeric(view["ecr"], errors="coerce").fillna(9999)
    return view.sort_values(["_ecr_sort", "vbd"], ascending=[True, False]).drop(
        columns="_ecr_sort"
    ).reset_index(drop=True)


if __name__ == "__main__":
    from pipeline.init_db import connect
    from pipeline.transform import player_season_view

    result = evaluate(player_season_view(connect()))
    print(result[["name", "position", "projected_points", "vbd", "tier", "adp_value"]].head(20))
