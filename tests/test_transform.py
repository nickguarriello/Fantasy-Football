import sqlite3

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
    result = transform.resolve_adp(conn)
    assert result["exact"] == 1
    row = conn.execute("SELECT adp FROM fact_adp WHERE player_id = 2").fetchone()
    assert row[0] == 8.0


def test_resolve_adp_fuzzy_fallback_for_suffixed_name():
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    result = transform.resolve_adp(conn)
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
    result = transform.resolve_adp(conn)
    assert result["exact"] == 0
    assert result["fuzzy"] == 0
