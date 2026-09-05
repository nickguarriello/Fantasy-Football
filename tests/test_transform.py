import sqlite3

import pandas as pd

from pipeline import init_db, transform


def _seed(conn):
    init_db.init_schema(conn)
    conn.executemany(
        "INSERT INTO dim_players (player_id, name, position) VALUES (?, ?, ?)",
        [
            (1, "James Cook III", "RB"),   # ESPN spells it with a suffix
            (2, "Amon-Ra St. Brown", "WR"),  # exact match case
        ],
    )
    conn.execute(
        "CREATE TABLE stg_sleeper_adp (name TEXT, position TEXT, pro_team TEXT, adp REAL)"
    )
    conn.executemany(
        "INSERT INTO stg_sleeper_adp (name, position, pro_team, adp) VALUES (?, ?, 'X', ?)",
        [
            ("James Cook", "RB", 25.0),        # Sleeper drops the suffix
            ("Amon-Ra St. Brown", "WR", 8.0),
        ],
    )
    conn.commit()


def test_resolve_adp_exact_match():
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    result = transform.resolve_adp(conn)["sleeper"]
    assert result["exact"] == 1
    row = conn.execute("SELECT adp FROM fact_adp WHERE player_id = 2").fetchone()
    assert row[0] == 8.0


def test_resolve_adp_fuzzy_fallback_for_suffixed_name():
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    result = transform.resolve_adp(conn)["sleeper"]
    assert result["fuzzy"] == 1
    row = conn.execute("SELECT adp FROM fact_adp WHERE player_id = 1").fetchone()
    assert row[0] == 25.0


def test_resolve_adp_does_not_cross_positions():
    """A same-name-different-position player must not steal another position's ADP."""
    conn = sqlite3.connect(":memory:")
    init_db.init_schema(conn)
    conn.execute("INSERT INTO dim_players (player_id, name, position) VALUES (1, 'Josh Allen', 'QB')")
    conn.execute(
        "CREATE TABLE stg_sleeper_adp (name TEXT, position TEXT, pro_team TEXT, adp REAL)"
    )
    conn.execute(
        "INSERT INTO stg_sleeper_adp (name, position, pro_team, adp) VALUES ('Josh Allen', 'LB', 'X', 250.0)"
    )
    conn.commit()
    result = transform.resolve_adp(conn)["sleeper"]
    assert result["exact"] == 0
    assert result["fuzzy"] == 0


def test_ffc_adp_wins_over_sleeper_when_both_present():
    """player_season_view coalesces ADP by source priority — FFC (real ADP) beats Sleeper (proxy)."""
    conn = sqlite3.connect(":memory:")
    init_db.init_schema(conn)
    conn.execute("INSERT INTO dim_players (player_id, name, position) VALUES (1, 'Bijan Robinson', 'RB')")
    for tbl in ("stg_ffc_adp", "stg_sleeper_adp"):
        conn.execute(f"CREATE TABLE {tbl} (name TEXT, position TEXT, pro_team TEXT, adp REAL)")
    conn.execute("INSERT INTO stg_ffc_adp VALUES ('Bijan Robinson', 'RB', 'ATL', 3.2)")
    conn.execute("INSERT INTO stg_sleeper_adp VALUES ('Bijan Robinson', 'RB', 'ATL', 1.0)")
    conn.commit()

    transform.resolve_adp(conn)
    view = transform.player_season_view(conn).set_index("player_id")
    assert view.loc[1, "adp"] == 3.2  # FFC, not Sleeper's 1.0


def test_sleeper_fills_in_when_ffc_missing_the_player():
    conn = sqlite3.connect(":memory:")
    init_db.init_schema(conn)
    conn.execute("INSERT INTO dim_players (player_id, name, position) VALUES (9, 'Deep Sleeper', 'WR')")
    for tbl in ("stg_ffc_adp", "stg_sleeper_adp"):
        conn.execute(f"CREATE TABLE {tbl} (name TEXT, position TEXT, pro_team TEXT, adp REAL)")
    conn.execute("INSERT INTO stg_sleeper_adp VALUES ('Deep Sleeper', 'WR', 'X', 180.0)")
    conn.commit()

    transform.resolve_adp(conn)
    view = transform.player_season_view(conn).set_index("player_id")
    assert view.loc[9, "adp"] == 180.0


def test_resolve_adp_dedupes_staged_rows_no_fanout():
    """A duplicated external entry must not fan out onto multiple players via the merge."""
    conn = sqlite3.connect(":memory:")
    init_db.init_schema(conn)
    conn.executemany(
        "INSERT INTO dim_players (player_id, name, position) VALUES (?, ?, ?)",
        [(1, "Puka Nacua", "WR"), (2, "Josh Allen", "QB")],
    )
    conn.execute("CREATE TABLE stg_ffc_adp (name TEXT, position TEXT, pro_team TEXT, adp REAL)")
    conn.executemany(
        "INSERT INTO stg_ffc_adp VALUES (?, ?, 'X', ?)",
        [("Puka Nacua", "WR", 4.0), ("Puka Nacua", "WR", 4.0), ("Josh Allen", "QB", 12.0)],
    )
    conn.commit()

    transform.resolve_adp(conn)
    rows = dict(conn.execute("SELECT player_id, adp FROM fact_adp").fetchall())
    assert rows == {1: 4.0, 2: 12.0}  # Allen keeps his own ADP, not Nacua's


def test_position_map_translates_def_and_pk():
    conn = sqlite3.connect(":memory:")
    init_db.init_schema(conn)
    conn.executemany(
        "INSERT INTO dim_players (player_id, name, position) VALUES (?, ?, ?)",
        [(1, "Rams D/ST", "DST"), (2, "Brandon Aubrey", "K")],
    )
    conn.execute("CREATE TABLE stg_ffc_adp (name TEXT, position TEXT, pro_team TEXT, adp REAL)")
    conn.executemany(
        "INSERT INTO stg_ffc_adp VALUES (?, ?, 'X', ?)",
        [("Rams D/ST", "DEF", 150.0), ("Brandon Aubrey", "PK", 120.0)],
    )
    conn.commit()

    transform.resolve_adp(conn)
    rows = dict(conn.execute("SELECT player_id, adp FROM fact_adp").fetchall())
    assert rows == {1: 150.0, 2: 120.0}
