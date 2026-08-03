"""SQLite schema + crosswalk seeding. The DB is ephemeral: rebuilt fresh each CI run."""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS dim_players (
    player_id   INTEGER PRIMARY KEY,   -- ESPN player id
    gsis_id     TEXT,                  -- nflverse/gsis id; NULL until crosswalked
    name        TEXT NOT NULL,
    position    TEXT,
    pro_team    TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS fact_roster (
    team_id     INTEGER NOT NULL,
    player_id   INTEGER NOT NULL,
    slot        TEXT,
    season      INTEGER NOT NULL,
    PRIMARY KEY (team_id, player_id, season)
);

CREATE TABLE IF NOT EXISTS fact_projection (
    player_id   INTEGER NOT NULL,
    season      INTEGER NOT NULL,
    week        INTEGER NOT NULL,      -- 0 = season total
    source      TEXT NOT NULL,         -- 'espn' | 'sleeper' | ...
    stat        TEXT NOT NULL,         -- stat abbrev, or 'points' for a precomputed total
    value       REAL,
    PRIMARY KEY (player_id, season, week, source, stat)
);

CREATE TABLE IF NOT EXISTS fact_actual (
    player_id   INTEGER NOT NULL,
    season      INTEGER NOT NULL,
    week        INTEGER NOT NULL,
    source      TEXT NOT NULL,
    stat        TEXT NOT NULL,
    value       REAL,
    PRIMARY KEY (player_id, season, week, source, stat)
);

CREATE TABLE IF NOT EXISTS fact_adp (
    player_id   INTEGER NOT NULL,
    season       INTEGER NOT NULL,
    source      TEXT NOT NULL,
    adp         REAL,
    PRIMARY KEY (player_id, season, source)
);

CREATE TABLE IF NOT EXISTS dim_schedule (
    pro_team    TEXT NOT NULL,
    season      INTEGER NOT NULL,
    week        INTEGER NOT NULL,
    opponent    TEXT,
    is_bye      INTEGER DEFAULT 0,
    PRIMARY KEY (pro_team, season, week)
);

CREATE TABLE IF NOT EXISTS fact_injury (
    player_id   INTEGER NOT NULL,
    season      INTEGER NOT NULL,
    week        INTEGER NOT NULL,
    status      TEXT,                 -- Q/D/O/IR/OUT/ACT
    PRIMARY KEY (player_id, season, week)
);

CREATE TABLE IF NOT EXISTS fact_vegas (
    pro_team        TEXT NOT NULL,
    season          INTEGER NOT NULL,
    week            INTEGER NOT NULL,
    implied_total   REAL,
    spread          REAL,
    game_total      REAL,
    PRIMARY KEY (pro_team, season, week)
);

CREATE TABLE IF NOT EXISTS dim_team (
    team_id     INTEGER NOT NULL,
    season      INTEGER NOT NULL,
    team_name   TEXT,
    PRIMARY KEY (team_id, season)
);

CREATE TABLE IF NOT EXISTS fact_draft_pick (
    pick_no     INTEGER NOT NULL,
    season      INTEGER NOT NULL,
    round       INTEGER,
    round_pick  INTEGER,
    team_id     INTEGER,
    team_name   TEXT,
    player_id   INTEGER,
    player_name TEXT,
    PRIMARY KEY (pick_no, season)
);

CREATE TABLE IF NOT EXISTS meta (
    key     TEXT PRIMARY KEY,
    value   TEXT
);
"""


def connect(db_path: Path = config.DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def seed_crosswalk(conn: sqlite3.Connection) -> int:
    """Load data/player-crosswalk.csv into dim_players if the table is empty. Returns rows loaded."""
    existing = conn.execute("SELECT COUNT(*) FROM dim_players").fetchone()[0]
    if existing:
        return 0
    if not config.CROSSWALK_CSV.exists():
        return 0

    rows = []
    with open(config.CROSSWALK_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(
                (
                    int(row["player_id"]),
                    row.get("gsis_id") or None,
                    row["name"],
                    row.get("position") or None,
                    row.get("pro_team") or None,
                )
            )
    conn.executemany(
        "INSERT OR IGNORE INTO dim_players (player_id, gsis_id, name, position, pro_team) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def main() -> None:
    config.DB_PATH.unlink(missing_ok=True)  # rebuilt fresh each run
    conn = connect()
    init_schema(conn)
    n = seed_crosswalk(conn)
    print(f"Initialized {config.DB_PATH} — seeded {n} crosswalk rows")
    conn.close()


if __name__ == "__main__":
    main()
