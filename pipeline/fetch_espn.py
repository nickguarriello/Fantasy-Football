"""ESPN fetch: league/rosters/matchups/settings + ESPN's own projections, via espn_api.

Current week is read from ESPN's own data (never date math — see DESIGN.md §7.1).
Wrapped in try/except per the graceful-degradation rule (§7.5): on failure, log and return
'skipped' rather than crashing the run; the last good DB/committed data stays live.

Pulls two overlapping player sets, both needed:
  - rosters (`team.roster`): who's owned, for in-season lineup/waiver features. Empty pre-draft.
  - player pool (`league.free_agents`): the full draftable universe with projections — this is
    what the draft board actually needs, and it's the *only* non-empty source before draft day.
Their union covers "every player worth valuing" whether pre- or post-draft.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

import config

PLAYER_POOL_SIZE = 700  # generous: covers the full fantasy-relevant universe, not just starters

# ESPN's own position labels don't all match ours (config.ROSTER_SLOTS uses "DST", not "D/ST") —
# normalize on the way in so every downstream lookup (VBD replacement level, etc.) matches.
POSITION_MAP = {"D/ST": "DST"}


def get_league():
    """Returns an espn_api.football.League, or None if creds/league_id are missing."""
    if not config.LEAGUE_ID or not config.ESPN_SWID or not config.ESPN_S2:
        print("fetch_espn: missing LEAGUE_ID or ESPN credentials — skipped")
        return None
    from espn_api.football import League  # imported lazily so the module imports creds-free

    return League(
        league_id=config.LEAGUE_ID,
        year=config.YEAR,
        espn_s2=config.ESPN_S2,
        swid=config.ESPN_SWID,
    )


def _safe_float(value) -> Optional[float]:
    """ESPN stat fields sometimes come back as dicts/containers instead of numbers — guard it."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def current_week(league) -> int:
    # espn_api exposes this as `current_week`; verify against the live payload if the library
    # version drifts (DESIGN.md §9 gotcha: period id != stat-category id).
    return getattr(league, "current_week", 0)


def _player_rows(player) -> tuple[tuple, list[tuple]]:
    """Returns (dim_players upsert row, [fact_projection rows]) for one espn_api Player."""
    position = getattr(player, "position", None)
    position = POSITION_MAP.get(position, position)
    player_row = (player.playerId, player.name, position, getattr(player, "proTeam", None))

    # player.stats: keyed by scoring-period id; period 0 = season total.
    # Each entry has 'breakdown' (actual) and 'projected_breakdown' (projection), keyed by stat abbrev.
    stats = getattr(player, "stats", {}) or {}
    season_stats = stats.get(0, {}) if isinstance(stats, dict) else {}
    projected = season_stats.get("projected_breakdown", {}) or {}
    projection_rows = []
    for stat_abbrev, raw_value in projected.items():
        val = _safe_float(raw_value)
        if val is None:
            continue
        projection_rows.append((player.playerId, config.YEAR, 0, "espn", stat_abbrev, val))
    return player_row, projection_rows


def _upsert_players(conn: sqlite3.Connection, players) -> int:
    player_rows, projection_rows = [], []
    for player in players:
        p_row, p_projections = _player_rows(player)
        player_rows.append(p_row)
        projection_rows.extend(p_projections)

    conn.executemany(
        """INSERT INTO dim_players (player_id, name, position, pro_team, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(player_id) DO UPDATE SET
             name=excluded.name, position=excluded.position,
             pro_team=excluded.pro_team, updated_at=excluded.updated_at""",
        player_rows,
    )
    conn.executemany(
        """INSERT OR REPLACE INTO fact_projection (player_id, season, week, source, stat, value)
           VALUES (?, ?, ?, ?, ?, ?)""",
        projection_rows,
    )
    conn.commit()
    return len(player_rows)


def fetch_rosters_and_projections(conn: sqlite3.Connection, league) -> dict:
    """Writes dim_players (upsert) + fact_roster + fact_projection(source='espn') for rostered
    players, and separately for the full player pool (draft board's real source pre-draft)."""
    if league is None:
        return {"status": "skipped", "reason": "no league"}

    week = current_week(league)

    roster_players, roster_rows = [], []
    for team in league.teams:
        for player in team.roster:
            roster_players.append(player)
            roster_rows.append((team.team_id, player.playerId, getattr(player, "lineupSlot", None), config.YEAR))
    rostered_count = _upsert_players(conn, roster_players)
    conn.executemany(
        "INSERT OR REPLACE INTO fact_roster (team_id, player_id, slot, season) VALUES (?, ?, ?, ?)",
        roster_rows,
    )

    pool = league.free_agents(size=PLAYER_POOL_SIZE)
    pool_count = _upsert_players(conn, pool)

    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('current_week', ?)", (str(week),)
    )
    conn.commit()
    return {
        "status": "ok",
        "rostered_players": rostered_count,
        "player_pool": pool_count,
        "current_week": week,
    }


def run(conn: sqlite3.Connection) -> dict:
    try:
        league = get_league()
        return fetch_rosters_and_projections(conn, league)
    except Exception as exc:  # noqa: BLE001 — graceful degradation, never crash the run
        print(f"fetch_espn: FAILED ({exc}) — preserving last good data")
        return {"status": "skipped", "reason": str(exc)}


if __name__ == "__main__":
    from pipeline.init_db import connect

    print(run(connect()))
