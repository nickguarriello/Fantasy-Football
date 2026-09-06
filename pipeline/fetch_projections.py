"""External projections + ADP. Sources are pluggable (DESIGN.md §8) so swapping/adding one
(e.g. FantasyPros consensus) doesn't touch valuation code in evaluate.py.

Each source function takes (conn) and returns a status dict; failures are non-fatal (§7.5).
"""
from __future__ import annotations

import json
import re
import sqlite3

import requests

import config

SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
# FantasyPros expert consensus (ECR) — the full draft board is embedded as `var ecrData = {...}`
# in the public half-PPR cheat-sheet page (≈950 players, 130+ experts, updated daily). The
# authenticated public API is the fallback but its free tier only returns ~10 rows/position.
FP_CHEATSHEET_URL = "https://www.fantasypros.com/nfl/rankings/half-point-ppr-cheatsheets.php"
FP_API_URL = "https://api.fantasypros.com/public/v2/json/nfl/{year}/consensus-rankings"
FP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
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


_FP_STG_DDL = (
    "CREATE TABLE IF NOT EXISTS stg_fp_ecr "
    "(name TEXT, position TEXT, pro_team TEXT, ecr REAL, ecr_pos TEXT, "
    " rank_min REAL, rank_max REAL, rank_ave REAL, rank_std REAL, fp_tier INTEGER, bye INTEGER)"
)


def _fp_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fp_rows_from_players(players: list[dict]) -> list[tuple]:
    rows = []
    for p in players:
        name = p.get("player_name")
        if not name or p.get("rank_ecr") is None:
            continue
        rows.append(
            (
                name,
                p.get("player_position_id"),
                p.get("player_team_id"),
                _fp_num(p.get("rank_ecr")),
                p.get("pos_rank"),
                _fp_num(p.get("rank_min")),
                _fp_num(p.get("rank_max")),
                _fp_num(p.get("rank_ave")),
                _fp_num(p.get("rank_std")),
                p.get("tier"),
                _fp_num(p.get("player_bye_week")),
            )
        )
    return rows


def _fp_scrape() -> list[dict]:
    resp = requests.get(FP_CHEATSHEET_URL, headers={"User-Agent": FP_UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    m = re.search(r"var\s+ecrData\s*=\s*(\{.*?\});", resp.text, re.DOTALL)
    if not m:
        raise ValueError("ecrData blob not found on cheat-sheet page")
    return json.loads(m.group(1)).get("players", [])


def _fp_api() -> list[dict]:
    key = config.FANTASYPROS_API_KEY
    if not key:
        raise ValueError("no FANTASYPROS_API_KEY for fallback")
    resp = requests.get(
        FP_API_URL.format(year=config.YEAR),
        params={"position": "OP", "scoring": "HALF", "type": "draft"},
        headers={"x-api-key": key},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("players", [])


def fetch_fantasypros_ecr(conn: sqlite3.Connection) -> dict:
    """Stage FantasyPros expert consensus rankings (overall ECR + the best/worst/avg/std spread
    across ~130 experts + FP's own tiers). Scrape the full cheat-sheet board first; on any
    failure fall back to the (thin) authenticated API. Non-fatal — evaluate.py degrades to the
    projection model when this is missing (§7.5)."""
    players, via = [], None
    try:
        players, via = _fp_scrape(), "scrape"
    except Exception as exc:  # noqa: BLE001
        print(f"fetch_fantasypros_ecr: scrape failed ({exc}) — trying API")
        try:
            players, via = _fp_api(), "api"
        except Exception as exc2:  # noqa: BLE001
            print(f"fetch_fantasypros_ecr: FAILED ({exc2}) — preserving last good data")
            return {"status": "skipped", "reason": str(exc2)}

    rows = _fp_rows_from_players(players)
    conn.execute(_FP_STG_DDL)
    conn.execute("DELETE FROM stg_fp_ecr")
    conn.executemany(
        "INSERT INTO stg_fp_ecr (name, position, pro_team, ecr, ecr_pos, rank_min, rank_max, "
        "rank_ave, rank_std, fp_tier, bye) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return {"status": "ok", "via": via, "rows": len(rows)}


SOURCES = {
    "ffc_adp": fetch_ffc_adp,
    "sleeper_adp": fetch_sleeper_adp,
    "fantasypros_ecr": fetch_fantasypros_ecr,
}


def run(conn: sqlite3.Connection) -> dict:
    return {name: fn(conn) for name, fn in SOURCES.items()}


if __name__ == "__main__":
    from pipeline.init_db import connect

    print(run(connect()))
