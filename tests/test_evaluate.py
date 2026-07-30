import pandas as pd

import config
from pipeline import evaluate


def test_projected_points_applies_scoring_config():
    row = pd.Series(
        {
            "proj_rushingYards": 100,
            "proj_rushingTouchdowns": 1,
            "proj_receivingReceptions": 5,
        }
    )
    pts = evaluate.projected_points(row)
    expected = (
        100 * config.SCORING["rush_yds"]
        + 1 * config.SCORING["rush_td"]
        + 5 * config.SCORING["rec"]
    )
    assert pts == round(expected, 2)


def test_projected_points_ignores_missing_stats():
    row = pd.Series({"proj_rushingYards": 50})
    assert evaluate.projected_points(row) == round(50 * config.SCORING["rush_yds"], 2)


def test_add_vbd_uses_replacement_level_player(monkeypatch):
    monkeypatch.setattr(config, "NUM_TEAMS", 2)
    monkeypatch.setattr(config, "ROSTER_SLOTS", {**config.ROSTER_SLOTS, "RB": 1, "FLEX": 0})
    monkeypatch.setattr(config, "FLEX_SHARE", {"RB": 0, "WR": 0, "TE": 0})

    view = pd.DataFrame(
        {
            "player_id": [1, 2, 3],
            "position": ["RB", "RB", "RB"],
            "projected_points": [200, 150, 100],
        }
    )
    result = evaluate.add_vbd(view).set_index("player_id")
    # N_pos = 2 teams x 1 starter = 2 -> replacement level = the 2nd-ranked RB (150 pts)
    assert result.loc[1, "vbd"] == 50
    assert result.loc[2, "vbd"] == 0
    assert result.loc[3, "vbd"] == -50


def test_add_tiers_breaks_on_big_gap():
    view = pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4],
            "position": ["WR"] * 4,
            "vbd": [100, 95, 40, 35],
        }
    )
    tiers = evaluate.add_tiers(view).set_index("player_id")["tier"]
    assert tiers[1] == tiers[2]
    assert tiers[3] == tiers[4]
    assert tiers[2] != tiers[3]


def test_add_adp_value_zero_when_adp_matches_vbd_rank():
    view = pd.DataFrame(
        {
            "player_id": [1, 2],
            "position": ["WR", "WR"],
            "vbd": [100, 50],
            "adp": [1, 2],
        }
    )
    result = evaluate.add_adp_value(view).set_index("player_id")
    assert result.loc[1, "adp_value"] == 0
    assert result.loc[2, "adp_value"] == 0


def test_add_adp_value_positive_gap_means_sleeper():
    """Going later (higher ADP number) than VBD rank suggests = a value target."""
    view = pd.DataFrame(
        {
            "player_id": [1, 2],
            "position": ["WR", "WR"],
            "vbd": [100, 50],
            "adp": [5, 2],  # player 1 is the top WR by value but goes 5th on ADP
        }
    )
    result = evaluate.add_adp_value(view).set_index("player_id")
    assert result.loc[1, "adp_value"] > 0
