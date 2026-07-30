"""Encodes the hard-won reliability lessons from DESIGN.md §7 as regression tests, so a future
edit can't silently reintroduce them.
"""
import inspect

from pipeline import fetch_espn


def test_current_week_is_not_derived_from_calendar():
    """§7.1 — Pitch Slap shipped a broken page for 16 days because 'current week' was date
    math that drifted. Current week must come from ESPN's own data, never datetime/date."""
    src = inspect.getsource(fetch_espn.current_week)
    assert "datetime" not in src
    assert "date.today" not in src
    assert "days" not in src


def test_fetch_espn_run_never_raises_on_failure():
    """§7.5 — graceful degradation: a flaky ESPN call must return a status dict, not throw,
    so one bad fetch doesn't crash main.py's whole run."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    result = fetch_espn.run(conn)  # no LEAGUE_ID/creds configured -> should skip, not raise
    assert result["status"] in ("skipped", "ok")
