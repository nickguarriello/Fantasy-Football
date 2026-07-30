"""Schedule/byes, injuries, snaps/targets, and Vegas lines via nfl-data-py (nflverse).

nflverse's schedule table already carries betting lines (spread_line/total_line) — no separate
Odds API call needed for v1. Each source is independently wrapped so one flaky pull (§7.5)
doesn't block the others.
"""
from __future__ import annotations

import sqlite3

import config


def _import():
    import nfl_data_py as nfl  # imported lazily so the module imports without the dep at test time

    return nfl


def fetch_schedule_and_vegas(conn: sqlite3.Connection) -> dict:
    try:
        nfl = _import()
        df = nfl.import_schedules([config.YEAR])
    except Exception as exc:  # noqa: BLE001
        print(f"fetch_nfl.schedule: FAILED ({exc}) — preserving last good data")
        return {"status": "skipped", "reason": str(exc)}

    sched_rows, vegas_rows = [], []
    for _, r in df.iterrows():
        week = int(r["week"]) if r.get("week") is not None else None
        if week is None:
            continue
        for side, opp_col in (("home_team", "away_team"), ("away_team", "home_team")):
            team, opp = r.get(side), r.get(opp_col)
            if team:
                sched_rows.append((team, config.YEAR, week, opp, 0))
        if r.get("home_team"):
            vegas_rows.append(
                (
                    r["home_team"],
                    config.YEAR,
                    week,
                    r.get("total_line", None) and float(r["total_line"]) / 2 + (float(r.get("spread_line", 0) or 0) / 2),
                    r.get("spread_line"),
                    r.get("total_line"),
                )
            )

    conn.executemany(
        "INSERT OR REPLACE INTO dim_schedule (pro_team, season, week, opponent, is_bye) VALUES (?, ?, ?, ?, ?)",
        sched_rows,
    )
    conn.executemany(
        """INSERT OR REPLACE INTO fact_vegas (pro_team, season, week, implied_total, spread, game_total)
           VALUES (?, ?, ?, ?, ?, ?)""",
        vegas_rows,
    )
    conn.commit()
    return {"status": "ok", "schedule_rows": len(sched_rows), "vegas_rows": len(vegas_rows)}


def fetch_injuries(conn: sqlite3.Connection) -> dict:
    try:
        nfl = _import()
        df = nfl.import_injuries([config.YEAR])
    except Exception as exc:  # noqa: BLE001
        print(f"fetch_nfl.injuries: FAILED ({exc}) — preserving last good data")
        return {"status": "skipped", "reason": str(exc)}

    conn.execute(
        "CREATE TABLE IF NOT EXISTS stg_injuries (gsis_id TEXT, week INTEGER, status TEXT)"
    )
    conn.execute("DELETE FROM stg_injuries")
    rows = [
        (r.get("gsis_id"), int(r["week"]), r.get("report_status"))
        for _, r in df.iterrows()
        if r.get("gsis_id") and r.get("week") is not None
    ]
    conn.executemany("INSERT INTO stg_injuries (gsis_id, week, status) VALUES (?, ?, ?)", rows)
    conn.commit()
    return {"status": "ok", "rows": len(rows)}


def fetch_usage(conn: sqlite3.Connection) -> dict:
    """Snap %, target share, etc. — staged for crosswalk.py / evaluate.py to join on gsis_id."""
    try:
        nfl = _import()
        df = nfl.import_snap_counts([config.YEAR])
    except Exception as exc:  # noqa: BLE001
        print(f"fetch_nfl.usage: FAILED ({exc}) — preserving last good data")
        return {"status": "skipped", "reason": str(exc)}

    conn.execute(
        "CREATE TABLE IF NOT EXISTS stg_snap_counts "
        "(gsis_id TEXT, week INTEGER, offense_pct REAL)"
    )
    conn.execute("DELETE FROM stg_snap_counts")
    rows = [
        (r.get("pfr_player_id"), int(r["week"]), r.get("offense_pct"))
        for _, r in df.iterrows()
        if r.get("week") is not None
    ]
    conn.executemany(
        "INSERT INTO stg_snap_counts (gsis_id, week, offense_pct) VALUES (?, ?, ?)", rows
    )
    conn.commit()
    return {"status": "ok", "rows": len(rows)}


def run(conn: sqlite3.Connection) -> dict:
    return {
        "schedule_vegas": fetch_schedule_and_vegas(conn),
        "injuries": fetch_injuries(conn),
        "usage": fetch_usage(conn),
    }


if __name__ == "__main__":
    from pipeline.init_db import connect

    print(run(connect()))
