"""Joins staged fetch output onto player_id; produces the season/weekly views evaluate.py consumes."""
from __future__ import annotations

import sqlite3

import pandas as pd

import config

# External sources spell the two team-defense / kicker positions their own way; our convention
# (fetch_espn.py) is DST / K. FFC uses DEF/PK, Sleeper uses DEF.
ADP_POSITION_MAP = {"DEF": "DST", "PK": "K"}
SLEEPER_POSITION_MAP = ADP_POSITION_MAP  # back-compat alias

# ADP sources in priority order: the first one that has a player wins. FFC is real mock-draft
# ADP; sleeper is a coarse search-popularity fallback for deep players FFC doesn't list.
ADP_SOURCES = [("ffc", "stg_ffc_adp"), ("sleeper", "stg_sleeper_adp")]


def _fuzzy_adp_matches(unmatched: pd.DataFrame, adp: pd.DataFrame, source: str, min_score=90, min_gap=5) -> list[tuple]:
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
        rows.append((int(p.player_id), config.YEAR, source, float(adp_val)))
    return rows


def _resolve_one_adp_source(conn: sqlite3.Connection, stg_table: str, source: str) -> dict:
    """Match one staged ADP table onto dim_players.player_id -> fact_adp: exact name+position
    match first, then a position-scoped fuzzy name fallback for the rest. Scoping by position
    (not just name) avoids a same-named player at a different position stealing another's ADP.
    De-dupes the staged rows by name+position (keeping the best/earliest ADP) so a duplicate
    external entry can't fan out onto multiple players in the merge."""
    has_stg = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (stg_table,)
    ).fetchone()
    if not has_stg:
        return {"status": "skipped", "reason": f"no {stg_table}"}

    players = pd.read_sql("SELECT player_id, name, position FROM dim_players", conn)
    players["_key"] = players["name"].str.strip().str.lower()
    adp = pd.read_sql(f"SELECT name, position, adp FROM {stg_table}", conn)
    if adp.empty:
        return {"status": "skipped", "reason": f"{stg_table} empty"}
    adp["_key"] = adp["name"].str.strip().str.lower()
    adp["position"] = adp["position"].replace(ADP_POSITION_MAP)
    adp = adp.sort_values("adp").drop_duplicates(["_key", "position"], keep="first")

    exact = adp.merge(players, on=["_key", "position"], suffixes=("_adp", "_player"))
    rows = [(int(r.player_id), config.YEAR, source, float(r.adp)) for r in exact.itertuples()]

    unmatched = players[~players["player_id"].isin(exact["player_id"])]
    fuzzy_rows = _fuzzy_adp_matches(unmatched, adp, source) if len(unmatched) else []
    rows.extend(fuzzy_rows)

    conn.executemany(
        "INSERT OR REPLACE INTO fact_adp (player_id, season, source, adp) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return {"status": "ok", "matched": len(rows), "exact": len(exact), "fuzzy": len(fuzzy_rows), "staged": len(adp)}


def resolve_adp(conn: sqlite3.Connection) -> dict:
    """Resolve every configured ADP source (ADP_SOURCES) into fact_adp, one row per source."""
    return {source: _resolve_one_adp_source(conn, stg, source) for source, stg in ADP_SOURCES}


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

    adp_all = pd.read_sql(
        "SELECT player_id, source, adp FROM fact_adp WHERE season = ?",
        conn,
        params=(config.YEAR,),
    )
    # Coalesce sources in ADP_SOURCES priority order (FFC real ADP first, Sleeper proxy as fill-in).
    priority = {source: i for i, (source, _) in enumerate(ADP_SOURCES)}
    adp_all["_pri"] = adp_all["source"].map(priority).fillna(len(priority))
    adp = (
        adp_all.sort_values("_pri")
        .drop_duplicates("player_id", keep="first")[["player_id", "adp"]]
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
