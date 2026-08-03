import json
import sqlite3

import config
from pipeline import init_db, report


def test_write_draft_state_reflects_teams_and_picks(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOCS_DATA_DIR", tmp_path / "docs_data")

    conn = sqlite3.connect(":memory:")
    init_db.init_schema(conn)
    conn.execute("INSERT INTO dim_team (team_id, season, team_name) VALUES (5, ?, 'Black Dog Tailwaggers')", (config.YEAR,))
    conn.execute(
        """INSERT INTO fact_draft_pick (pick_no, season, round, round_pick, team_id, team_name, player_id, player_name)
           VALUES (1, ?, 1, 1, 5, 'Black Dog Tailwaggers', 111, 'Jahmyr Gibbs')""",
        (config.YEAR,),
    )
    conn.commit()

    report.write_draft_state(conn)

    data = json.loads((tmp_path / "docs_data" / "draft-state.json").read_text(encoding="utf-8"))
    assert data["drafted"] is True
    assert data["teams"] == [{"team_id": 5, "team_name": "Black Dog Tailwaggers"}]
    assert data["picks"][0]["player_name"] == "Jahmyr Gibbs"


def test_write_draft_state_pre_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOCS_DATA_DIR", tmp_path / "docs_data")
    conn = sqlite3.connect(":memory:")
    init_db.init_schema(conn)

    report.write_draft_state(conn)

    data = json.loads((tmp_path / "docs_data" / "draft-state.json").read_text(encoding="utf-8"))
    assert data["drafted"] is False
    assert data["picks"] == []
