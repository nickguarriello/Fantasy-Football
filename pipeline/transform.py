"""Joins staged fetch output onto player_id; produces the season/weekly views evaluate.py consumes."""
from __future__ import annotations

import sqlite3

import pandas as pd

import config


def resolve_adp(conn: sqlite3.Connection) -> dict:
    """Match staged Sleeper ADP rows (by name) onto dim_players.player_id -> fact_adp."""
    has_stg = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stg_sleeper_adp'"
    ).fetchone()
    if not has_stg:
        return {"status": "skipped", "reason": "no staged ADP"}

    players = pd.read_sql("SELECT player_id, name FROM dim_players", conn)
    players["_key"] = players["name"].str.strip().str.lower()
    adp = pd.read_sql("SELECT name, adp FROM stg_sleeper_adp", conn)
    adp["_key"] = adp["name"].str.strip().str.lower()

    merged = adp.merge(players, on="_key", suffixes=("_adp", "_player"))
    rows = [
        (int(r.player_id), config.YEAR, "sleeper", float(r.adp))
        for r in merged.itertuples()
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO fact_adp (player_id, season, source, adp) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return {"status": "ok", "matched": len(rows), "staged": len(adp)}


def player_season_view(conn: sqlite3.Connection) -> pd.DataFrame:
    """One row per player: identity + pivoted ESPN season projections + ADP + bye week."""
    players = pd.read_sql(
        "SELECT player_id, name, position, pro_team, gsis_id FROM dim_players", conn
    )

    proj = pd.read_sql(
        "SELECT player_id, stat, value FROM fact_projection WHERE season = ? AND week = 0 AND source = 'espn'",
        conn,
        params=(config.YEAR,),
    )
    proj_wide = proj.pivot_table(index="player_id", columns="stat", values="value", aggfunc="first")
    proj_wide.columns = [f"proj_{c}" for c in proj_wide.columns]

    adp = pd.read_sql(
        "SELECT player_id, adp FROM fact_adp WHERE season = ? AND source = 'sleeper'",
        conn,
        params=(config.YEAR,),
    )

    byes = pd.read_sql(
        "SELECT pro_team, week AS bye_week FROM dim_schedule WHERE season = ? AND is_bye = 1",
        conn,
        params=(config.YEAR,),
    )

    view = players.merge(proj_wide, on="player_id", how="left")
    view = view.merge(adp, on="player_id", how="left")
    view = view.merge(byes, on="pro_team", how="left")
    return view


def run(conn: sqlite3.Connection) -> dict:
    adp_result = resolve_adp(conn)
    view = player_season_view(conn)
    return {"adp": adp_result, "season_view_rows": len(view)}


if __name__ == "__main__":
    from pipeline.init_db import connect

    print(run(connect()))
