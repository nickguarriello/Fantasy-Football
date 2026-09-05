"""FFC ADP fetch — real mock-draft ADP scoped to the league format. `requests.get` is stubbed
so the test is offline; the payload shape mirrors fantasyfootballcalculator.com/api/v1/adp.
"""
import sqlite3

import pytest

import config
from pipeline import fetch_projections, init_db


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    init_db.init_schema(c)
    return c


def test_fetch_ffc_adp_stages_rows_and_scopes_to_league(conn, monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _FakeResp(
            {
                "status": "Success",
                "players": [
                    {"name": "Ja'Marr Chase", "position": "WR", "team": "CIN", "adp": 1.4},
                    {"name": "Bijan Robinson", "position": "RB", "team": "ATL", "adp": 2.1},
                    {"name": "No ADP Guy", "position": "WR", "team": "X", "adp": None},
                ],
            }
        )

    monkeypatch.setattr(fetch_projections.requests, "get", fake_get)
    result = fetch_projections.fetch_ffc_adp(conn)

    assert result == {"status": "ok", "rows": 2}  # the None-adp row is dropped
    assert captured["params"] == {"teams": config.NUM_TEAMS, "year": config.YEAR}
    staged = conn.execute("SELECT name, adp FROM stg_ffc_adp ORDER BY adp").fetchall()
    assert staged == [("Ja'Marr Chase", 1.4), ("Bijan Robinson", 2.1)]


def test_fetch_ffc_adp_network_failure_is_non_fatal(conn, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(fetch_projections.requests, "get", boom)
    result = fetch_projections.fetch_ffc_adp(conn)
    assert result["status"] == "skipped"


def test_fetch_sleeper_adp_drops_unranked_sentinel(conn, monkeypatch):
    payload = {
        "1": {"full_name": "Real Player", "position": "RB", "team": "DET", "search_rank": 5},
        "2": {"full_name": "Bench Warmer", "position": "RB", "team": "X", "search_rank": 9999999},
        "3": {"full_name": "No Rank", "position": "WR", "team": "X", "search_rank": None},
    }
    monkeypatch.setattr(fetch_projections.requests, "get", lambda *a, **k: _FakeResp(payload))
    result = fetch_projections.fetch_sleeper_adp(conn)

    assert result == {"status": "ok", "rows": 1}
    staged = conn.execute("SELECT name FROM stg_sleeper_adp").fetchall()
    assert staged == [("Real Player",)]
