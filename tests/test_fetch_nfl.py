"""Regression: fetch_schedule_and_vegas used to hardcode is_bye=0 for every row, so bye_week
was always blank on the dashboard no matter what data came back. Tested here with a synthetic
schedule (a 3-team round robin, one bye per team) since nfl_data_py can't be installed in this
sandbox (Python 3.14 has no numpy<2.0 wheel) — the real column names (week/home_team/away_team/
game_type/total_line/spread_line) were verified against a real CI run (schedule_rows: 544).
"""
import sqlite3
from types import SimpleNamespace

import pandas as pd
import pytest

import config
from pipeline import fetch_nfl, init_db


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    init_db.init_schema(c)
    return c


def _fake_schedule_df():
    # 3-team round robin over 3 weeks: exactly one bye per team.
    rows = [
        {"week": 1, "home_team": "A", "away_team": "B", "game_type": "REG", "total_line": 44.0, "spread_line": -3.0},
        {"week": 2, "home_team": "A", "away_team": "C", "game_type": "REG", "total_line": 42.0, "spread_line": 2.5},
        {"week": 3, "home_team": "B", "away_team": "C", "game_type": "REG", "total_line": 40.0, "spread_line": -1.0},
    ]
    return pd.DataFrame(rows)


def test_bye_weeks_computed_correctly(conn, monkeypatch):
    fake_module = SimpleNamespace(import_schedules=lambda years: _fake_schedule_df())
    monkeypatch.setattr(fetch_nfl, "_import", lambda: fake_module)

    result = fetch_nfl.fetch_schedule_and_vegas(conn)
    assert result["status"] == "ok"

    byes = conn.execute(
        "SELECT pro_team, week FROM dim_schedule WHERE season = ? AND is_bye = 1 ORDER BY pro_team",
        (config.YEAR,),
    ).fetchall()
    assert byes == [("A", 3), ("B", 2), ("C", 1)]


def test_playoff_rows_do_not_create_false_byes(conn, monkeypatch):
    """A team eliminated from playoffs has no playoff-week row — that must not look like a bye."""
    df = pd.concat(
        [
            _fake_schedule_df(),
            pd.DataFrame(
                [{"week": 4, "home_team": "A", "away_team": "B", "game_type": "WC", "total_line": 45.0, "spread_line": -2.0}]
            ),
        ],
        ignore_index=True,
    )
    fake_module = SimpleNamespace(import_schedules=lambda years: df)
    monkeypatch.setattr(fetch_nfl, "_import", lambda: fake_module)

    fetch_nfl.fetch_schedule_and_vegas(conn)

    # C didn't make the playoff-week (WC) row, but that's week 4 which is outside the REG-only
    # bye computation (max_week=3) — must not be reported as a bye.
    c_byes = conn.execute(
        "SELECT week FROM dim_schedule WHERE season = ? AND pro_team = 'C' AND is_bye = 1", (config.YEAR,)
    ).fetchall()
    assert c_byes == [(1,)]
