"""External projections + ADP. Sources are pluggable (DESIGN.md §8) so swapping/adding one
(e.g. FantasyPros consensus) doesn't touch valuation code in evaluate.py.

Each source function takes (conn) and returns a status dict; failures are non-fatal (§7.5).
"""
from __future__ import annotations

import sqlite3

import requests

import config

SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
# Fantasy Football Calculator: free, no-auth, real mock-draft ADP (not a popularity proxy).
# Format/teams are matched to the league so the ADP reflects our exact draft shape.
FFC_ADP_URL = "https://fantasyfootballcalculator.com/api/v1/adp/half-ppr"
SLEEPER_UNRANKED = 9999999  # Sleeper's sentinel for "not draft-relevant" — not a real rank
TIMEOUT = 20


def fetch_ffc_adp(conn: sqlite3.Connection) -> dict:
    """Fantasy Football Calculator ADP — real average draft position from public mock drafts,
    scoped to our league's format (half-PPR) and team count. Primary ADP source; Sleeper's
    search_rank (below) is a coarse fallback for players FFC's ~200-deep board doesn't list.
    Staged by name/position; transform.resolve_adp assigns the ESPN player_id.
    """
    try:
        resp = requests.get(
            FFC_ADP_URL, params={"teams": config.NUM_TEAMS, "year": config.YEAR}, timeout=TIMEOUT
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"fetch_ffc_adp: FAILED ({exc}) — preserving last good data")
        return {"status": "skipped", "reason": str(exc)}

    players = payload.get("players") or []
    rows = [
        (p["name"], p.get("position"), p.get("team"), p["adp"])
        for p in players
        if p.get("name") and p.get("adp") is not None
    ]
    conn.execute(
        "CREATE TABLE IF NOT EXISTS stg_ffc_adp (name TEXT, position TEXT, pro_team TEXT, adp REAL)"
    )
    conn.execute("DELETE FROM stg_ffc_adp")
    conn.executemany(
        "INSERT INTO stg_ffc_adp (name, position, pro_team, adp) VALUES (?, ?, ?, ?)", rows
    )
    conn.commit()
    return {"status": "ok", "rows": len(rows)}


def fetch_sleeper_adp(conn: sqlite3.Connection) -> dict:
    """Sleeper's public player endpoint exposes `search_rank` (a search-popularity ordering, not
    true ADP). Kept as a *fallback* only — for deep players FFC doesn't rank — since it's still
    a reasonable ordinal. transform.resolve_adp prefers FFC where both exist.
    """
    try:
        resp = requests.get(SLEEPER_PLAYERS_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        players = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"fetch_sleeper_adp: FAILED ({exc}) — preserving last good data")
        return {"status": "skipped", "reason": str(exc)}

    # Sleeper keys by its own player_id and doesn't expose ESPN ids directly; crosswalk.py
    # resolves player_id via name matching in a later pass, so we stage rows by name here
    # and let crosswalk assign espn player_id where unambiguous.
    rows = []
    for p in players.values():
        rank = p.get("search_rank")
        if rank is None or rank >= SLEEPER_UNRANKED or not p.get("full_name"):
            continue
        rows.append((p["full_name"], p.get("position"), p.get("team"), rank))

    conn.execute(
        "CREATE TABLE IF NOT EXISTS stg_sleeper_adp "
        "(name TEXT, position TEXT, pro_team TEXT, adp REAL)"
    )
    conn.execute("DELETE FROM stg_sleeper_adp")
    conn.executemany(
        "INSERT INTO stg_sleeper_adp (name, position, pro_team, adp) VALUES (?, ?, ?, ?)", rows
    )
    conn.commit()
    return {"status": "ok", "rows": len(rows)}


SOURCES = {
    "ffc_adp": fetch_ffc_adp,
    "sleeper_adp": fetch_sleeper_adp,
}


def run(conn: sqlite3.Connection) -> dict:
    return {name: fn(conn) for name, fn in SOURCES.items()}


if __name__ == "__main__":
    from pipeline.init_db import connect

    print(run(connect()))
