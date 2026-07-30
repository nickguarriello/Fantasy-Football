"""Output *completeness* checks (DESIGN.md §7.3). Catches silent degradation — a run that
"succeeds" but ships an incomplete page. Distinct from validate.py, which gates on integrity.

Called twice by the workflow (§7.4): once non-fatally at the end of main.py, and again as a
final step *after* docs/data is committed+pushed, so a degraded run still publishes AND alerts.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import config

EXPECTED_OUTPUT_FILES = ["draft-board.json", "validation-report.json"]
FRESHNESS_HOURS = 48


def _check_output_files() -> dict:
    missing, empty = [], []
    for name in EXPECTED_OUTPUT_FILES:
        path = config.DOCS_DATA_DIR / name
        if not path.exists():
            missing.append(name)
        elif path.stat().st_size == 0:
            empty.append(name)
    if missing or empty:
        return {"check": "output_files", "status": "fail",
                "detail": f"missing={missing} empty={empty}"}
    return {"check": "output_files", "status": "ok", "detail": f"{len(EXPECTED_OUTPUT_FILES)} files present"}


def _check_draft_board_populated() -> dict:
    path = config.DOCS_DATA_DIR / "draft-board.json"
    if not path.exists():
        return {"check": "draft_board_populated", "status": "fail", "detail": "draft-board.json missing"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"check": "draft_board_populated", "status": "fail", "detail": f"invalid JSON: {exc}"}
    players = data.get("players", []) if isinstance(data, dict) else data
    status = "ok" if len(players) >= 50 else "degraded"
    return {"check": "draft_board_populated", "status": status, "detail": f"{len(players)} players on board"}


def _check_stats_fresh(db_path: Path) -> dict:
    if not db_path.exists():
        return {"check": "stats_fresh", "status": "fail", "detail": "no DB found"}
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT MAX(updated_at) FROM dim_players").fetchone()
    finally:
        conn.close()
    updated_at = row[0] if row else None
    status = "ok" if updated_at else "degraded"
    return {"check": "stats_fresh", "status": status, "detail": f"last updated_at={updated_at}"}


def run(db_path: Path = config.DB_PATH, write: bool = True) -> dict:
    checks = [
        _check_output_files(),
        _check_draft_board_populated(),
        _check_stats_fresh(db_path),
    ]
    degraded_checks = [c["check"] for c in checks if c["status"] in ("degraded", "fail")]
    result = {
        "overall": "degraded" if degraded_checks else "ok",
        "degraded_checks": degraded_checks,
        "checks": checks,
    }
    if write:
        config.DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.DOCS_DATA_DIR / "health.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    return result


if __name__ == "__main__":
    result = run(write=False)
    for c in result["checks"]:
        print(f"[{c['status'].upper():8}] {c['check']}: {c['detail']}")
    print(f"overall: {result['overall']}")
    sys.exit(1 if result["overall"] == "degraded" else 0)
