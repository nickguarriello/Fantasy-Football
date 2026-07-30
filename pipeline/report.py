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
