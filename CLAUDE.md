# AI session guardrails

Read [DESIGN.md](DESIGN.md) first — it's the source of truth for architecture and the reliability
playbook (§7). This file is boundaries only.

## No-touch list (don't weaken without explicit ask)

- `.github/workflows/pipeline.yml` step order — commit-then-alert (§7.4) only works if the health
  check runs *after* the data commit/push. Don't reorder.
- `validate.py` — never remove a check or turn a FAIL into a WARN to unblock a run. Fix the data
  or the check, don't loosen the gate.
- `data/player-crosswalk.csv` columns (`player_id,gsis_id,name,position,pro_team`) — `init_db.py`
  and `crosswalk.py` both depend on this exact header.
- The `validate` (blocking) vs `health` (non-fatal, alerting) split — don't merge them or make
  health fatal; that defeats "publish first, alert after" (§7.4).
- `current_week()` in `pipeline/fetch_espn.py` — must stay derived from ESPN's own data, never
  date/calendar math (§7.1 — this exact mistake caused a 16-day outage on the prior project).

## Working agreed

- Small diffs. One phase/feature per session where possible.
- Update [PLANNING.md](PLANNING.md) at the end of every session — what shipped, what's next,
  anything you'd want a fresh session to know.
- Snapshot `config.py` before changing it: `python config.py --snapshot`.
- Don't commit locally-regenerated `docs/data/*.json` or `fantasy.db` — the scheduled CI run is
  the source of truth for the live site. Local runs are for preview/testing only.
- Don't force-push `main`.
- Real ESPN stat-abbreviation keys (`STAT_MAP` in `pipeline/evaluate.py`) and the live-draft-pick
  API (§12.6) are unverified assumptions — inspect a live payload before trusting them blindly.
