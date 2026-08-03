"""Writes docs/data/*.json — the only thing the static site reads."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import config


def _write(name: str, payload: dict) -> None:
    config.DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.DOCS_DATA_DIR / name, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)


def write_draft_board(board: dict) -> None:
    _write("draft-board.json", board)


def write_draft_state(conn: sqlite3.Connection) -> None:
    """docs/data/draft-state.json — auto-synced from ESPN's live draft feed (fetch_espn.py).
    assistant.html merges this with any picks marked manually client-side since the last run,
    so the assistant stays usable even between pipeline runs during a live draft."""
    teams = conn.execute(
        "SELECT team_id, team_name FROM dim_team WHERE season = ? ORDER BY team_name", (config.YEAR,)
    ).fetchall()
    picks = conn.execute(
        """SELECT pick_no, round, round_pick, team_id, team_name, player_id, player_name
           FROM fact_draft_pick WHERE season = ? ORDER BY pick_no""",
        (config.YEAR,),
    ).fetchall()
    pick_cols = ["pick_no", "round", "round_pick", "team_id", "team_name", "player_id", "player_name"]
    _write(
        "draft-state.json",
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "season": config.YEAR,
            "drafted": len(picks) > 0,
            "teams": [{"team_id": t[0], "team_name": t[1]} for t in teams],
            "picks": [dict(zip(pick_cols, p)) for p in picks],
        },
    )


def write_meta(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT value FROM meta WHERE key = 'current_week'").fetchone()
    _write(
        "meta.json",
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "season": config.YEAR,
            "current_week": int(row[0]) if row else None,
        },
    )
