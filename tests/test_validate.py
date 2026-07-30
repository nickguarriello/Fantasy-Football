import sqlite3

from pipeline import init_db, validate


def _fresh_conn():
    conn = sqlite3.connect(":memory:")
    init_db.init_schema(conn)
    return conn


def test_fails_on_empty_db():
    results = validate.run(_fresh_conn(), write=False)
    checks = {r["check"]: r["status"] for r in results}
    assert checks["players_present"] == "fail"
    assert checks["projections_present"] == "fail"


def test_passes_players_present_once_seeded():
    conn = _fresh_conn()
    conn.execute(
        "INSERT INTO dim_players (player_id, name, position) VALUES (1, 'Test Player', 'RB')"
    )
    conn.commit()
    results = validate.run(conn, write=False)
    checks = {r["check"]: r["status"] for r in results}
    assert checks["players_present"] == "pass"
    assert checks["no_duplicate_players"] == "pass"


def test_crosswalk_coverage_warns_below_threshold():
    conn = _fresh_conn()
    conn.executemany(
        "INSERT INTO dim_players (player_id, name, position, gsis_id) VALUES (?, ?, 'RB', ?)",
        [(1, "A", None), (2, "B", None)],
    )
    conn.executemany(
        "INSERT INTO fact_roster (team_id, player_id, slot, season) VALUES (1, ?, 'RB', 2026)",
        [(1,), (2,)],
    )
    conn.commit()
    results = validate.run(conn, write=False)
    checks = {r["check"]: r["status"] for r in results}
    assert checks["crosswalk_coverage"] == "warn"
