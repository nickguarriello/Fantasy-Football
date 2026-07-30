"""External projections + ADP. Sources are pluggable (DESIGN.md §8) so swapping/adding one
(e.g. FantasyPros consensus) doesn't touch valuation code in evaluate.py.

Each source function takes (conn) and returns a status dict; failures are non-fatal (§7.5).
"""
from __future__ import annotations

import sqlite3

import requests

import config

SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
TIMEOUT = 20


def fetch_sleeper_adp(conn: sqlite3.Connection) -> dict:
    """Sleeper's public player endpoint exposes `search_rank`, used here as an ADP proxy.
    TODO: verify against a dedicated ADP endpoint / mock-draft source once available — see
    DESIGN.md §12 open question on projection/ADP sourcing.
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
        if rank is None or not p.get("full_name"):
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
    "sleeper_adp": fetch_sleeper_adp,
}


def run(conn: sqlite3.Connection) -> dict:
    return {name: fn(conn) for name, fn in SOURCES.items()}


if __name__ == "__main__":
    from pipeline.init_db import connect

    print(run(connect()))
