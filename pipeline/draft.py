"""Draft board (Phase 1, priority) + live best-available assistant (Phase 2 - basic version;
DESIGN.md §12.6 flags "does ESPN expose live draft picks via API?" as unresearched, so this
takes a manual `drafted_ids` list as the fallback input path).
"""
from __future__ import annotations

import pandas as pd

import config


def positional_scarcity(view: pd.DataFrame) -> dict:
    """Steepness of the VBD dropoff at each position: top starter's VBD minus the VBD just past
    the startable tier. Bigger = scarcer = prioritize before a run (DESIGN.md §6.5)."""
    scarcity = {}
    for position, group in view.groupby("position"):
        ranked = group.sort_values("vbd", ascending=False).reset_index(drop=True)
        starters = config.ROSTER_SLOTS.get(position, 1) * config.NUM_TEAMS
        if len(ranked) <= starters:
            scarcity[position] = 0.0
            continue
        top_vbd = ranked.loc[0, "vbd"]
        cutoff_vbd = ranked.loc[min(starters, len(ranked) - 1), "vbd"]
        scarcity[position] = round(float(top_vbd - cutoff_vbd), 2)
    return scarcity


def bye_clusters(roster_view: pd.DataFrame, threshold: int = 3) -> list[dict]:
    """Flags bye weeks where >= `threshold` rostered starters share the same bye."""
    if "bye_week" not in roster_view.columns:
        return []
    counts = roster_view.dropna(subset=["bye_week"]).groupby("bye_week").size()
    return [
        {"week": int(week), "count": int(n)}
        for week, n in counts.items()
        if n >= threshold
    ]


def build_board(evaluated_view: pd.DataFrame) -> dict:
    """evaluated_view = output of evaluate.evaluate(). Returns the draft-board.json payload."""
    cols = [
        "player_id", "name", "position", "pro_team", "bye_week",
        "projected_points", "vbd", "vbd_rank", "tier", "adp", "adp_value",
    ]
    players = evaluated_view[[c for c in cols if c in evaluated_view.columns]].copy()
    # astype(object) first: on a float64 column, .where(..., None) silently recoerces None back
    # to NaN, which json.dump then writes as the bare (invalid-JSON) token `NaN` — breaks
    # JSON.parse in the browser. object dtype lets None actually stick, serializing as `null`.
    players = players.astype(object).where(players.notna(), None)
    return {
        "season": config.YEAR,
        "num_teams": config.NUM_TEAMS,
        "scoring": config.SCORING,
        "scarcity": positional_scarcity(evaluated_view),
        "players": players.to_dict("records"),
    }


def best_available(
    evaluated_view: pd.DataFrame,
    drafted_ids: set[int],
    my_roster_positions: dict | None = None,
    n: int = 10,
) -> pd.DataFrame:
    """Remaining players ranked by VBD, lightly reweighted for positional need.

    `my_roster_positions`: {"RB": 1, "WR": 0, ...} count of starters already filled — positions
    already at their starter count get a small penalty so the assistant doesn't over-stack.
    """
    available = evaluated_view[~evaluated_view["player_id"].isin(drafted_ids)].copy()
    my_roster_positions = my_roster_positions or {}

    def need_adjustment(position: str) -> float:
        filled = my_roster_positions.get(position, 0)
        starters = config.ROSTER_SLOTS.get(position, 0)
        return 0.0 if filled < starters else -2.0  # small nudge, not a hard filter

    available["need_adjusted_vbd"] = available["vbd"] + available["position"].map(need_adjustment)
    return available.sort_values("need_adjusted_vbd", ascending=False).head(n)


def positional_run_alert(recent_picks: list[str], window: int = 5, threshold: int = 3) -> str | None:
    """recent_picks: list of positions for the last N overall picks, most recent last."""
    recent = recent_picks[-window:]
    for position in set(recent):
        if recent.count(position) >= threshold:
            return f"Run on {position}: {recent.count(position)} of the last {len(recent)} picks"
    return None


if __name__ == "__main__":
    from pipeline.init_db import connect
    from pipeline.transform import player_season_view
    from pipeline.evaluate import evaluate

    board = build_board(evaluate(player_season_view(connect())))
    print(f"{len(board['players'])} players, scarcity={board['scarcity']}")
