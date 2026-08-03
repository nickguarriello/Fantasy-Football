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
