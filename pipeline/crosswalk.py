"""ESPN-ID <-> nflverse/gsis-ID crosswalk, with daily self-heal (DESIGN.md §7.2).

Runs right after fetch each pipeline run. Resolution order for any rostered/relevant player
still missing a gsis_id:
  1. data/crosswalk-overrides.json (manual, for ambiguous/renamed players)
  2. nflverse's own id crosswalk (nfl_data_py.import_ids) — exact espn_id match
  3. exact name match against that same table
  4. unique fuzzy name match (rapidfuzz) — only accepted if unambiguous
Anything still unresolved is returned as `unresolved` and logged. Non-fatal: validate.py
remains the gate, not this step — roster churn / call-ups should never block a run.
"""
from __future__ import annotations

import csv
import json
import sqlite3

import config


def _load_overrides() -> dict:
    if not config.CROSSWALK_OVERRIDES.exists():
        return {}
    with open(config.CROSSWALK_OVERRIDES, encoding="utf-8") as f:
        return json.load(f)


def _load_id_reference():
    """nflverse's own multi-source id crosswalk. Returns list of {espn_id, gsis_id, name} dicts."""
    import nfl_data_py as nfl

    df = nfl.import_ids()
    df = df[["espn_id", "gsis_id", "name"]].dropna(subset=["gsis_id", "name"])
    return df.to_dict("records")


def heal(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT player_id, name FROM dim_players WHERE gsis_id IS NULL"
    ).fetchall()
    if not rows:
        return {"status": "ok", "resolved": 0, "unresolved": []}

    overrides = _load_overrides()
    try:
        reference = _load_id_reference()
    except Exception as exc:  # noqa: BLE001 — non-fatal per §7.5
        print(f"crosswalk.heal: reference load FAILED ({exc}) — overrides-only this run")
        reference = []

    by_espn_id = {r["espn_id"]: r for r in reference if r.get("espn_id")}
    by_name = {r["name"].strip().lower(): r for r in reference}

    resolved, unresolved = [], []
    for player_id, name in rows:
        gsis_id = None

        override = overrides.get(str(player_id))
        if override and override.get("gsis_id"):
            gsis_id = override["gsis_id"]
        elif str(player_id) in by_espn_id or player_id in by_espn_id:
            gsis_id = by_espn_id.get(str(player_id), by_espn_id.get(player_id))["gsis_id"]
        elif name.strip().lower() in by_name:
            gsis_id = by_name[name.strip().lower()]["gsis_id"]
        else:
            gsis_id = _fuzzy_match(name, reference)

        if gsis_id:
            resolved.append((player_id, gsis_id, name))
        else:
            unresolved.append({"player_id": player_id, "name": name})

    if resolved:
        conn.executemany(
            "UPDATE dim_players SET gsis_id = ? WHERE player_id = ?",
            [(gsis_id, player_id) for player_id, gsis_id, _ in resolved],
        )
        conn.commit()
        _append_to_csv(resolved)

    if unresolved:
        print(f"crosswalk.heal: {len(unresolved)} players still unresolved: "
              f"{[u['name'] for u in unresolved]}")

    return {"status": "ok", "resolved": len(resolved), "unresolved": unresolved}


def _fuzzy_match(name: str, reference: list[dict], min_score: int = 90, min_gap: int = 5):
    if not reference:
        return None
    from rapidfuzz import process, fuzz

    choices = [r["name"] for r in reference]
    matches = process.extract(name, choices, scorer=fuzz.WRatio, limit=2)
    if not matches:
        return None
    top_name, top_score, _ = matches[0]
    if top_score < min_score:
        return None
    if len(matches) > 1 and (top_score - matches[1][1]) < min_gap:
        return None  # ambiguous — two close candidates, don't guess
    for r in reference:
        if r["name"] == top_name:
            return r["gsis_id"]
    return None


def _append_to_csv(resolved: list[tuple]) -> None:
    """Self-improve the committed seed so future runs need less healing."""
    existing_ids = set()
    if config.CROSSWALK_CSV.exists():
        with open(config.CROSSWALK_CSV, newline="", encoding="utf-8") as f:
            existing_ids = {row["player_id"] for row in csv.DictReader(f)}

    new_rows = [
        {"player_id": str(pid), "gsis_id": gid, "name": name, "position": "", "pro_team": ""}
        for pid, gid, name in resolved
        if str(pid) not in existing_ids
    ]
    if not new_rows:
        return

    write_header = not config.CROSSWALK_CSV.exists()
    with open(config.CROSSWALK_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["player_id", "gsis_id", "name", "position", "pro_team"])
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)


if __name__ == "__main__":
    from pipeline.init_db import connect

    print(heal(connect()))
