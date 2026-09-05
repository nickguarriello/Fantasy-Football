import json

import numpy as np
import pandas as pd

from pipeline import draft


def test_build_board_serializes_missing_values_as_json_null_not_nan():
    """Regression: on a float64 column, `.where(notna, None)` silently recoerces None back to
    NaN, and json.dump then writes the bare (invalid-JSON) token `NaN`, which breaks
    JSON.parse in the browser. Caught live: players missing an ADP match (e.g. suffixed names
    like 'James Cook III') broke the whole draft board page."""
    view = pd.DataFrame(
        {
            "player_id": [1, 2],
            "name": ["Has ADP", "Missing ADP"],
            "position": ["RB", "RB"],
            "pro_team": ["AAA", "BBB"],
            "bye_week": [9, np.nan],
            "projected_points": [200.0, 150.0],
            "vbd": [50.0, 10.0],
            "vbd_rank": [1.0, 2.0],
            "tier": [1, 1],
            "adp": [3.0, np.nan],
            "adp_value": [-2.0, np.nan],
        }
    )
    board = draft.build_board(view)
    serialized = json.dumps(board)  # strict JSON — raises/produces bad output on bare NaN

    assert "NaN" not in serialized
    missing = board["players"][1]
    assert missing["adp"] is None
    assert missing["adp_value"] is None
    assert missing["bye_week"] is None


def test_build_board_blanks_adp_value_for_one_slot_positions():
    """QB/K/DST adp_value is a mirage (VBD overrates 1-slot pools) — build_board nulls it so the
    board can't invite a reach. Skill-position adp_value is left intact."""
    view = pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4],
            "name": ["Elite QB", "A Kicker", "A Defense", "A Back"],
            "position": ["QB", "K", "DST", "RB"],
            "pro_team": ["BUF", "DAL", "PIT", "ATL"],
            "bye_week": [7, 7, 9, 5],
            "projected_points": [380.0, 140.0, 120.0, 240.0],
            "vbd": [90.0, 0.0, 0.0, 55.0],
            "vbd_rank": [4.0, 300.0, 300.0, 6.0],
            "tier": [1, 1, 1, 2],
            "adp": [31.0, 130.0, 150.0, 12.0],
            "adp_value": [27.0, -170.0, -150.0, 6.0],
        }
    )
    by_id = {p["player_id"]: p for p in draft.build_board(view)["players"]}
    assert by_id[1]["adp_value"] is None   # QB
    assert by_id[2]["adp_value"] is None   # K
    assert by_id[3]["adp_value"] is None   # DST
    assert by_id[4]["adp_value"] == 6.0    # RB untouched
