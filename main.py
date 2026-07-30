"""Orchestrator. Runs the shared pipeline spine (DESIGN.md §5), then draft-board evaluation.

--mode full   everything: ESPN + projections + nfl-data-py (schedule/vegas/injuries/usage)
--mode light  ESPN + projections only — faster local iteration, skips the slower nfl-data-py pulls
"""
from __future__ import annotations

import argparse
import sys

import config
from pipeline import (
    crosswalk,
    draft,
    evaluate as evaluate_mod,
    fetch_espn,
    fetch_nfl,
    fetch_projections,
    health,
    init_db,
    report,
    transform,
    validate,
)


def main(mode: str) -> int:
    conn = init_db.connect()
    init_db.init_schema(conn)
    init_db.seed_crosswalk(conn)

    print("== fetch_espn ==")
    print(fetch_espn.run(conn))

    print("== fetch_projections ==")
    print(fetch_projections.run(conn))

    if mode == "full":
        print("== fetch_nfl ==")
        print(fetch_nfl.run(conn))

    print("== crosswalk.heal ==")
    print(crosswalk.heal(conn))

    print("== transform ==")
    print(transform.run(conn))

    print("== validate ==")
    validation_results = validate.run(conn)
    for r in validation_results:
        print(f"  [{r['status'].upper():4}] {r['check']}: {r['detail']}")
    if any(r["status"] == "fail" for r in validation_results):
        print("validate: FAIL — blocking run, not publishing")
        conn.close()
        return 1

    print("== evaluate + draft board ==")
    view = transform.player_season_view(conn)
    evaluated = evaluate_mod.evaluate(view)
    board = draft.build_board(evaluated)
    report.write_draft_board(board)
    report.write_meta(conn)
    print(f"  wrote draft-board.json ({len(board['players'])} players)")

    conn.close()

    # Non-fatal: health failures don't block the run, they just get logged (workflow's
    # final health step is what turns the CI job red — see DESIGN.md §7.4).
    try:
        result = health.run()
        print(f"== health: {result['overall']} ({result['degraded_checks']}) ==")
    except Exception as exc:  # noqa: BLE001
        print(f"health check itself failed (non-fatal): {exc}")

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "light"], default="full")
    args = parser.parse_args()
    sys.exit(main(args.mode))
