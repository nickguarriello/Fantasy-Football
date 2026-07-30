"""Data *integrity* checks (DESIGN.md §7.3). Any FAIL blocks the run — don't publish garbage.
WARN is non-blocking. Distinct from health.py, which checks output *completeness*.
"""
from __future__ import annotations

import json
import sqlite3
import sys

import config

CROSSWALK_WARN_THRESHOLD = 0.90  # WARN if < 90% of rostered players have a gsis_id


def check_players_present(conn: sqlite3.Connection) -> dict:
    n = conn.execute("SELECT COUNT(*) FROM dim_players").fetchone()[0]
    status = "pass" if n > 0 else "fail"
    return {"check": "players_present", "status": status, "detail": f"{n} players in dim_players"}


def check_no_duplicate_players(conn: sqlite3.Connection) -> dict:
    dupes = conn.execute(
        "SELECT player_id, COUNT(*) c FROM dim_players GROUP BY player_id HAVING c > 1"
    ).fetchall()
    status = "pass" if not dupes else "fail"
    return {"check": "no_duplicate_players", "status": status, "detail": f"{len(dupes)} duplicate player_ids"}


def check_crosswalk_coverage(conn: sqlite3.Connection) -> dict:
    rostered = conn.execute("SELECT COUNT(DISTINCT player_id) FROM fact_roster").fetchone()[0]
    if rostered == 0:
        return {"check": "crosswalk_coverage", "status": "warn", "detail": "no rostered players to check"}
    covered = conn.execute(
        """SELECT COUNT(DISTINCT r.player_id) FROM fact_roster r
           JOIN dim_players p ON p.player_id = r.player_id
           WHERE p.gsis_id IS NOT NULL"""
    ).fetchone()[0]
    pct = covered / rostered
    status = "pass" if pct >= CROSSWALK_WARN_THRESHOLD else "warn"
    return {
        "check": "crosswalk_coverage",
        "status": status,
        "detail": f"{covered}/{rostered} rostered players crosswalked ({pct:.0%})",
    }


def check_projections_present(conn: sqlite3.Connection) -> dict:
    n = conn.execute(
        "SELECT COUNT(*) FROM fact_projection WHERE season = ? AND source = 'espn'", (config.YEAR,)
    ).fetchone()[0]
    status = "pass" if n > 0 else "fail"
    return {"check": "projections_present", "status": status, "detail": f"{n} ESPN projection rows"}


CHECKS = [
    check_players_present,
    check_no_duplicate_players,
    check_crosswalk_coverage,
    check_projections_present,
]


def run(conn: sqlite3.Connection, write: bool = True) -> list[dict]:
    results = [check(conn) for check in CHECKS]
    if write:
        config.DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.DOCS_DATA_DIR / "validation-report.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
    return results


if __name__ == "__main__":
    from pipeline.init_db import connect

    results = run(connect())
    for r in results:
        print(f"[{r['status'].upper():4}] {r['check']}: {r['detail']}")
    if any(r["status"] == "fail" for r in results):
        sys.exit(1)
