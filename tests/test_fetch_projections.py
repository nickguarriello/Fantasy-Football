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

    @property
    def text(self):
        return self._payload if isinstance(self._payload, str) else ""


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


_FP_HTML = (
    "<html><head></head><body><script>\n"
    'var ecrData = {"sport":"NFL","type":"Draft Half PPR","year":"2026","players":['
    '{"player_name":"Jahmyr Gibbs","player_position_id":"RB","player_team_id":"DET",'
    '"rank_ecr":1,"rank_min":"1","rank_max":"5","rank_ave":"1.53","rank_std":"0.68",'
    '"pos_rank":"RB1","tier":1,"player_bye_week":"6"},'
    '{"player_name":"Rams D/ST","player_position_id":"DST","player_team_id":"LAR",'
    '"rank_ecr":190,"rank_min":"150","rank_max":"230","rank_ave":"188.0","rank_std":"20.0",'
    '"pos_rank":"DST5","tier":8,"player_bye_week":"11"},'
    '{"player_name":"No Rank Guy","player_position_id":"WR","rank_ecr":null}'
    "]};\n</script></body></html>"
)


def test_fetch_fantasypros_ecr_parses_embedded_blob(conn, monkeypatch):
    monkeypatch.setattr(
        fetch_projections.requests, "get", lambda *a, **k: _FakeResp(_FP_HTML)
    )
    result = fetch_projections.fetch_fantasypros_ecr(conn)
    assert result["status"] == "ok" and result["via"] == "scrape"
    assert result["rows"] == 2  # the null-rank_ecr row is dropped
    staged = conn.execute("SELECT name, position, ecr, rank_std FROM stg_fp_ecr ORDER BY ecr").fetchall()
    assert staged[0] == ("Jahmyr Gibbs", "RB", 1.0, 0.68)


def test_fetch_fantasypros_ecr_scrape_fail_falls_back_to_api(conn, monkeypatch):
    calls = {"n": 0}

    def fake_get(url, **k):
        calls["n"] += 1
        if "fantasypros.com/nfl/rankings" in url:
            raise RuntimeError("blocked")
        return _FakeResp({"players": [
            {"player_name": "Josh Allen", "player_position_id": "QB", "player_team_id": "BUF",
             "rank_ecr": 20, "rank_min": "12", "rank_max": "35", "rank_std": "6.0", "tier": 3}
        ]})

    monkeypatch.setattr(fetch_projections.config, "FANTASYPROS_API_KEY", "test-key")
    monkeypatch.setattr(fetch_projections.requests, "get", fake_get)
    result = fetch_projections.fetch_fantasypros_ecr(conn)
    assert result == {"status": "ok", "via": "api", "rows": 1}
    assert calls["n"] == 2  # scrape attempted, then API


def test_fetch_fantasypros_ecr_all_paths_fail_is_non_fatal(conn, monkeypatch):
    monkeypatch.setattr(fetch_projections.config, "FANTASYPROS_API_KEY", None)
    monkeypatch.setattr(fetch_projections.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert fetch_projections.fetch_fantasypros_ecr(conn)["status"] == "skipped"


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
