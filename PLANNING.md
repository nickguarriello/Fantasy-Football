# Planning log

Running build log — update every session. Newest entry on top.

---

## 2026-07-30 — Live league settings pulled from ESPN; scoring CORRECTED (committed 2026-08-03)

Configured the real league and pulled settings live from `league.settings` (the authoritative
source), which **corrects the entry below**:
- `LEAGUE_ID = 1152031` set (+ ESPN creds configured locally, gitignored).
- **Scoring is half-PPR (`rec: 0.5`), 4-pt passing TD** — NOT the full-PPR/6-pt entered verbally
  below. league.settings wins over a verbal guess (data-over-assumption). `config.py` snapshotted
  first (2 snapshots in `config_history/`).
- Roster corrected off the §13 defaults: BENCH 7→5, IR 1→2. Added confirmed facts for Phase 3:
  `REG_SEASON_WEEKS=14`, `PLAYOFF_TEAM_COUNT=7`, `PLAYOFF_MATCHUP_WEEKS=1`, `WAIVER_TYPE=priority`,
  `TRADE_DEADLINE=2026-12-04`.
- `fetch_espn.py`: added the **full player pool** (`league.free_agents(size=700)`) as a second
  source alongside rosters — `team.roster` is empty pre-draft, so the pool is the draft board's
  only real data source before draft day. Refactored the player/projection upsert into
  `_player_rows`/`_upsert_players`; added `POSITION_MAP` (D/ST→DST) so positions match
  `ROSTER_SLOTS`. `current_week()` unchanged — still ESPN-derived (§7.1 guardrail respected).
- `tests/test_smoke.py`: hardened the creds-fallback test to force the ImportError via monkeypatch
  rather than depending on the file being absent.

Verified: `pytest` 32/32.

**Next (now unblocked by having creds + LEAGUE_ID):**
1. **Verify `evaluate.py` STAT_MAP against a live ESPN payload** — flagged as an unverified guess;
   now that creds exist, inspect real `projected_breakdown` abbrevs and correct before trusting the
   board's point totals. Highest priority — gates draft-board accuracy.
2. First real pipeline run against the configured league to populate `docs/data/*.json`.
3. Sanity-check the Sleeper ADP `search_rank` proxy vs real ADP.
4. Local full-mode still needs a 3.11/3.12 venv (numpy/cp314 wheel issue).

---

## 2026-07-30 — League settings confirmed: 12 teams, full PPR, 6-pt pass TD  ⚠️ SUPERSEDED (see above — scoring was actually half-PPR/4-pt, per live league.settings)

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
