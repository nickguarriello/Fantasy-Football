"""Joins staged fetch output onto player_id; produces the season/weekly views evaluate.py consumes."""
from __future__ import annotations

import sqlite3

import pandas as pd

import config

SLEEPER_POSITION_MAP = {"DEF": "DST"}  # Sleeper calls it DEF; our convention (fetch_espn.py) is DST


def _fuzzy_adp_matches(unmatched: pd.DataFrame, adp: pd.DataFrame, min_score=90, min_gap=5) -> list[tuple]:
    """Position-scoped fuzzy fallback for names an exact match misses (e.g. suffixes: Sleeper's
    'James Cook' vs ESPN's 'James Cook III'). Position-scoped both to cut the candidate pool and
    to avoid cross-position false positives. Only accepted when unambiguous, same rule as
    crosswalk.py's fuzzy match: top score >= min_score AND a clear gap over the runner-up."""
    from rapidfuzz import fuzz, process

    rows = []
    adp_by_pos = {pos: g[["name", "adp"]].drop_duplicates("name") for pos, g in adp.groupby("position")}
    for p in unmatched.itertuples():
        pool = adp_by_pos.get(p.position)
        if pool is None or pool.empty:
            continue
        matches = process.extract(p.name, pool["name"].tolist(), scorer=fuzz.WRatio, limit=2)
        if not matches:
            continue
        top_name, top_score, _ = matches[0]
        if top_score < min_score:
            continue
        if len(matches) > 1 and (top_score - matches[1][1]) < min_gap:
            continue  # ambiguous — two close candidates, don't guess
        adp_val = pool.loc[pool["name"] == top_name, "adp"].iloc[0]
        rows.append((int(p.player_id), config.YEAR, "sleeper", float(adp_val)))
    return rows


def resolve_adp(conn: sqlite3.Connection) -> dict:
    """Match staged Sleeper ADP rows onto dim_players.player_id -> fact_adp: exact
    name+position match first, then a position-scoped fuzzy name fallback for the rest.
    Scoping by position (not just name) avoids a same-named player at a different position
    stealing another player's ADP."""
    has_stg = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stg_sleeper_adp'"
    ).fetchone()
    if not has_stg:
        return {"status": "skipped", "reason": "no staged ADP"}

    players = pd.read_sql("SELECT player_id, name, position FROM dim_players", conn)
    players["_key"] = players["name"].str.strip().str.lower()
    adp = pd.read_sql("SELECT name, position, adp FROM stg_sleeper_adp", conn)
    adp["_key"] = adp["name"].str.strip().str.lower()
    adp["position"] = adp["position"].replace(SLEEPER_POSITION_MAP)

    exact = adp.merge(players, on=["_key", "position"], suffixes=("_adp", "_player"))
    rows = [(int(r.player_id), config.YEAR, "sleeper", float(r.adp)) for r in exact.itertuples()]

    unmatched = players[~players["player_id"].isin(exact["player_id"])]
    fuzzy_rows = _fuzzy_adp_matches(unmatched, adp) if len(unmatched) else []
    rows.extend(fuzzy_rows)

    conn.executemany(
        "INSERT OR REPLACE INTO fact_adp (player_id, season, source, adp) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return {"status": "ok", "matched": len(rows), "exact": len(exact), "fuzzy": len(fuzzy_rows), "staged": len(adp)}


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
