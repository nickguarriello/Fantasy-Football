import sqlite3

from pipeline import fetch_espn, init_db


class _FakeTeam:
    def __init__(self, team_id, team_name):
        self.team_id = team_id
        self.team_name = team_name


class _FakePick:
    def __init__(self, team, player_id, player_name, round_num, round_pick):
        self.team = team
        self.playerId = player_id
        self.playerName = player_name
        self.round_num = round_num
        self.round_pick = round_pick


class _FakeLeague:
    """Duck-types just what fetch_draft_picks touches — no real espn_api/network needed."""

    def __init__(self, picks):
        self._picks = picks
        self.draft = []
        self.refresh_calls = 0

    def refresh_draft(self):
        self.refresh_calls += 1
        self.draft = list(self._picks)


def _fresh_conn():
    conn = sqlite3.connect(":memory:")
    init_db.init_schema(conn)
    return conn


def test_fetch_draft_picks_writes_rows_in_pick_order():
    team = _FakeTeam(5, "Black Dog Tailwaggers")
    league = _FakeLeague([_FakePick(team, 111, "Jahmyr Gibbs", 1, 1), _FakePick(team, 222, "Josh Allen", 1, 2)])
    conn = _fresh_conn()

    result = fetch_espn.fetch_draft_picks(conn, league)

    assert result == {"status": "ok", "picks": 2}
    rows = conn.execute(
        "SELECT pick_no, player_id, player_name, team_name FROM fact_draft_pick ORDER BY pick_no"
    ).fetchall()
    assert rows == [(1, 111, "Jahmyr Gibbs", "Black Dog Tailwaggers"), (2, 222, "Josh Allen", "Black Dog Tailwaggers")]


def test_fetch_draft_picks_resets_before_each_refresh():
    """Regression: espn_api's _fetch_draft() APPENDS to league.draft rather than replacing it —
    polling refresh_draft() repeatedly would accumulate duplicates unless we reset first."""
    team = _FakeTeam(5, "Black Dog Tailwaggers")
    league = _FakeLeague([_FakePick(team, 111, "Jahmyr Gibbs", 1, 1)])
    conn = _fresh_conn()

    fetch_espn.fetch_draft_picks(conn, league)
    league._picks.append(_FakePick(team, 222, "Josh Allen", 1, 2))
    fetch_espn.fetch_draft_picks(conn, league)  # simulates a second poll mid-draft

    rows = conn.execute("SELECT player_id FROM fact_draft_pick ORDER BY pick_no").fetchall()
    assert rows == [(111,), (222,)]  # not [(111,), (111,), (222,)]


def test_fetch_draft_picks_empty_pre_draft():
    league = _FakeLeague([])
    conn = _fresh_conn()
    result = fetch_espn.fetch_draft_picks(conn, league)
    assert result == {"status": "ok", "picks": 0}


def test_fetch_draft_picks_skipped_without_league():
    conn = _fresh_conn()
    assert fetch_espn.fetch_draft_picks(conn, None) == {"status": "skipped", "reason": "no league"}
