import config


def test_num_teams_positive():
    assert config.NUM_TEAMS > 0


def test_flex_share_sums_to_one():
    assert abs(sum(config.FLEX_SHARE.values()) - 1.0) < 1e-6


def test_flex_share_only_covers_flex_eligible_positions():
    assert set(config.FLEX_SHARE) <= {"RB", "WR", "TE"}


def test_scoring_values_numeric():
    assert all(isinstance(v, (int, float)) for v in config.SCORING.values())


def test_roster_slots_non_negative():
    assert all(v >= 0 for v in config.ROSTER_SLOTS.values())
