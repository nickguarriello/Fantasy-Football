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


def test_add_consensus_value_risk_ceiling():
    view = pd.DataFrame({
        "player_id": [1, 2, 3, 4],
        "name": ["Falls past ECR", "Solid", "Polarizing", "No ECR"],
        "position": ["WR", "RB", "RB", "WR"],
        "adp": [40.0, 10.0, 100.0, 55.0],
        "ecr": [18.0, 9.0, 90.0, pd.NA],
        "ecr_pos": ["WR8", "RB4", "RB33", pd.NA],
        "rank_min": [11.0, 7.0, 45.0, pd.NA],
        "rank_max": [30.0, 14.0, 180.0, pd.NA],
        "rank_std": [3.0, 3.5, 41.0, pd.NA],
        "fp_tier": [2, 1, 8, pd.NA],
    })
    out = evaluate.add_consensus(view).set_index("player_id")
    assert out.loc[1, "value_vs_ecr"] == 22.0          # ADP 40 - ECR 18
    assert out.loc[1, "risk"] == "Safe"                # std 3 vs expected ~5.7
    assert out.loc[1, "ceiling"]                       # rank_min 11 well above ECR 18
    assert out.loc[3, "risk"] == "Volatile"            # std 41 vs expected ~16.5
    assert out.loc[4, "risk"] in (None,) or pd.isna(out.loc[4, "risk"])  # no ECR -> no bucket
    assert bool(out.loc[4, "ceiling"]) is False
    assert pd.isna(out.loc[4, "value_vs_ecr"])


def test_add_consensus_no_ecr_columns_at_all():
    """The whole ECR merge can be absent (fetch skipped) — add_consensus must still produce the
    columns, all null, without raising."""
    view = pd.DataFrame({
        "player_id": [1], "name": ["X"], "position": ["RB"], "adp": [12.0], "vbd": [30.0],
    })
    out = evaluate.add_consensus(view)
    for col in ("ecr", "value_vs_ecr", "risk", "ceiling"):
        assert col in out.columns


def test_add_tiers_elite_outliers_do_not_wash_out_later_breaks():
    """Regression: the old running-mean threshold let a couple of huge top-of-position gaps
    inflate the average so far that no later break fired — producing one 15-deep RB tier 1.
    With a median yardstick, the tight mid-pack still splits into multiple tiers."""
    # Two elite RBs far ahead, then a tight pack, then a clear cliff, then another pack.
    vbds = [85, 60, 40, 22, 21, 20, 19.5, 19, 12, 11.5, 11, 10.5]
    view = pd.DataFrame(
        {"player_id": list(range(len(vbds))), "position": ["RB"] * len(vbds), "vbd": vbds}
    )
    tiers = evaluate.add_tiers(view).set_index("player_id")["tier"]
    assert tiers.nunique() >= 4              # not one lumped tier
    assert tiers.value_counts().max() <= 6   # no single mega-tier
    assert tiers[0] != tiers[1]              # the two elite RBs are tiered apart from each other
    assert tiers[7] != tiers[8]             # the cliff after the first pack starts a new tier


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
