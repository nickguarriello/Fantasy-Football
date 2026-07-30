# Planning log

Running build log — update every session. Newest entry on top.

---

## 2026-07-30 — League settings confirmed: 12 teams, full PPR, 6-pt pass TD

Answered part of the §12 open-questions backlog. Updated `config.py` (snapshotted first, per
[CLAUDE.md](CLAUDE.md)) and `DESIGN.md` §12/§13:
- 12 teams (already the default — confirmed, no change).
- Single QB, not superflex (already the default — confirmed, no change).
- **Full PPR** (`rec: 1`, was half-PPR `0.5`).
- **6-point passing TD** (`pass_td: 6`, was 4).

Verified: `pytest` still 32/32 (tests compute expected values from `config.SCORING` dynamically,
so they didn't need updating for the scoring change).

**Still open before the draft board is real** (§12): `LEAGUE_ID` + ESPN credentials (needed to
fetch anything at all), remaining roster slot confirmation (RB/WR/TE/FLEX/K/DST counts, bench/IR
size — still on the §13 defaults), draft date, and whether there's a TE premium or other scoring
quirks beyond what's now confirmed.

---

## 2026-07-30 — Phase 0 + Phase 1 scaffold

Scaffolded the repo per [DESIGN.md](DESIGN.md) §14 (Phase 0 spine + Phase 1 draft board).

**Shipped:**
- Repo init (git, `main` branch), `.gitignore`, `requirements.txt`/`requirements-dev.txt`.
- `config.py` — league settings, half-PPR scoring, 12-team/standard-roster defaults (§13),
  `--snapshot` helper.
- `pipeline/` spine: `init_db`, `fetch_espn`, `fetch_projections` (Sleeper ADP), `fetch_nfl`
  (nflverse schedule/vegas/injuries/snaps), `crosswalk` (self-heal), `transform`, `validate`
  (blocking), `health` (non-fatal), `evaluate` (projected points/VBD/tiers/ADP value), `draft`
  (board + basic best-available), `report` (writes `docs/data/*.json`).
- `main.py` orchestrator (`--mode full|light`).
- `docs/` dashboard shell — dark theme, shared nav (`assets/nav.js`), health banner. `draft.html`
  is fully functional (sortable/filterable table, tier badges, ADP-value coloring, "my need"
  highlighting). Other pages (`assistant`, `startsit`, `waivers`, `matchup`, `trades`, `playoff`)
  are Phase 2/3 placeholders. `log.html` renders `validation-report.json` + `health.json`.
- `tests/` — 32 tests: import smoke (creds-free), config invariants, evaluate/VBD/tier math,
  validate checks, health checks, and two guardrail regression tests encoding the §7.1/§7.5
  reliability lessons directly (current-week-not-from-calendar, fetch never raises).
- `.github/workflows/tests.yml` and `pipeline.yml` per §7.4/§7.7.
- `CLAUDE.md`, seed `data/player-crosswalk.csv` (header only) + `data/crosswalk-overrides.json`.

**Verified locally:**
- `pytest` — 32/32 pass.
- `python main.py --mode light` end-to-end with no ESPN creds configured: fetch_espn skips
  gracefully, Sleeper ADP fetch pulled ~12k real rows, crosswalk/transform ran, `validate`
  correctly FAILED (no players/projections without a real league) and blocked publish — the
  gate works as designed.
- `draft.html` rendering, filtering, and sorting verified in-browser against sample JSON.

**Known gaps / next session:**
1. **§12 open questions still block a real draft board**: `LEAGUE_ID`, actual roster slots,
   team count, and confirmed scoring (half-PPR assumed) need to be filled into `config.py`.
2. `evaluate.py`'s `STAT_MAP` (ESPN stat-abbrev -> scoring key) is a best guess from espn_api
   conventions — **unverified against a live payload**. Inspect once `LEAGUE_ID`/creds exist and
   correct before trusting the draft board's point totals.
3. Sleeper ADP source uses `search_rank` as a proxy (no official public ADP endpoint found) —
   flagged in `fetch_projections.py`; revisit if ADP values look off.
4. `nfl-data-py`/`espn_api` weren't pip-installable in the local dev sandbox (Python 3.14 — numpy
   pin lacks a cp314 wheel, no compiler available to build from source). Not a CI problem (workflows
   pin Python 3.11), but local full-mode runs need a 3.11/3.12 venv until numpy ships 3.14 wheels.
   Both modules are imported lazily specifically so smoke tests don't need them installed.
5. Phase 2 (live draft assistant) research item still open: does ESPN expose live draft picks via
   API, or is manual mark-drafted the only path? `draft.py:best_available()` currently assumes
   manual input.
6. `docs/*.json` are empty (`.gitkeep` only) until the first real pipeline run against a
   configured league.
