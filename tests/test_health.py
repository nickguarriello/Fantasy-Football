import config
from pipeline import health


def test_degraded_when_no_outputs_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOCS_DATA_DIR", tmp_path / "docs_data")
    result = health.run(db_path=tmp_path / "nonexistent.db", write=False)
    assert result["overall"] == "degraded"
    assert "output_files" in result["degraded_checks"]


def test_ok_when_outputs_present_and_populated(tmp_path, monkeypatch):
    import json
    import sqlite3

    docs_data = tmp_path / "docs_data"
    docs_data.mkdir()
    (docs_data / "draft-board.json").write_text(
        json.dumps({"players": [{"name": f"p{i}"} for i in range(60)]})
    )
    (docs_data / "validation-report.json").write_text("[]")
    monkeypatch.setattr(config, "DOCS_DATA_DIR", docs_data)

    db_path = tmp_path / "fantasy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE dim_players (player_id INTEGER, updated_at TEXT)"
    )
    conn.execute("INSERT INTO dim_players VALUES (1, datetime('now'))")
    conn.commit()
    conn.close()

    result = health.run(db_path=db_path, write=False)
    assert result["overall"] == "ok"
