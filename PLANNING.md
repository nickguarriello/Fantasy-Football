# Planning log

Running build log — update every session. Newest entry on top.

---

## 2026-08-03 — Bye weeks fixed (were always blank — real bug, not a data gap)

`fetch_nfl.fetch_schedule_and_vegas` wrote every `dim_schedule` row with `is_bye` hardcoded to
`0` — bye weeks were never actually computed, so `bye_week` was blank on the draft board
regardless of whether `nfl_data_py` returned data. Confirmed live: the last CI run pulled 544
schedule rows successfully, but 0/700 players had a bye_week set. Fixed by computing each team's
bye as the week(s) missing from their `game_type == 'REG'` rows; verified with a synthetic
3-team round-robin (real `nfl_data_py` still can't install locally — Python 3.14 has no
numpy<2.0 wheel). Re-ran the live pipeline: **609/700 players now have a bye_week**.

Remaining 91 missing: 51 are free agents with no `pro_team` (correct — no team, no bye), but
**21 LAR + 19 WSH players are real mismatches** — ESPN's team-abbreviation code for the Rams
and/or Washington likely doesn't match nflverse's (e.g. WSH vs WAS is a known inconsistency
between NFL data providers). Not fixed yet — need to inspect nflverse's actual `home_team`/
`away_team` codes for these two teams (can't verify locally without `nfl_data_py`; check via a
real CI log or a temporary debug print) before guessing at a `POSITION_MAP`-style translation.

---

## 2026-08-03 — Live on GitHub Pages; Phase 2 draft assistant built; ADP fuzzy match added

**Site is live**: https://nickguarriello.github.io/Fantasy-Football/ (public repo — required for
free-tier Pages; nothing sensitive is in the codebase, `espn_credentials.py` stays local/gitignored).

**GitHub setup** (installed `gh` CLI via winget since it wasn't present; several device-flow auth
attempts expired before landing — codes need to be used within GitHub's ~15min window):
- Repo created, pushed, Pages enabled (`main`/`docs`).
- `ESPN_SWID`/`ESPN_S2` set as repo secrets (piped directly from local `espn_credentials.py` into
  `gh secret set`, never printed).
- First `workflow_dispatch` run **failed**: `requirements.txt` pinned `pandas>=2.2`, but
  `nfl-data-py` (0.3.3, latest on PyPI) requires `pandas<2.0` — pip's resolver had no solution.
  Fixed by relaxing to `pandas<2.0,>=1.5`; nothing in the pipeline used a pandas-2.x-only API.
  Re-run succeeded: 700 real players, `validate` all PASS, `health` ok, live on the site.
  `nfl_data_py`'s injuries/snap-count endpoints 404'd (probably not published this early
  pre-season) — degraded gracefully exactly as designed, non-fatal.

**Three follow-up items tackled together** (user: "let's tackle all 3 now"):
1. **Re-verified roster slots/scoring against `league.settings`** — unchanged from the prior
   session's live pull (12 teams, half-PPR, 4-pt pass TD, bench 5/IR 2); no config change needed.
2. **Fixed ADP name matching** ([pipeline/transform.py](pipeline/transform.py)): `resolve_adp()`
   only did an exact lowercased-name join, missing suffixed names (ESPN's "James Cook III" vs
   Sleeper's "James Cook") and — a second bug my own test caught — not scoping by position at all,
   so a same-named player at a different position could steal another player's ADP. Fixed with a
   name+position exact join, then a position-scoped fuzzy fallback (same unambiguous-only rule as
   `crosswalk.py`). Real match rate: 611/700 exact → 656/700 total (45 fuzzy). Also maps Sleeper's
   `DEF` label to our `DST` convention.
3. **Researched + built Phase 2 (live draft assistant)**, resolving DESIGN.md §12.6:
   - Read `espn_api`'s source directly (not just docs): `league.draft` / `league.refresh_draft()`
     hits ESPN's real `mDraftDetail` view and **does** expose live picks — auto-sync is real, no
     manual-only fallback needed. Undocumented gotcha found in the source: `_fetch_draft()`
     *appends* to `league.draft` instead of replacing it, so polling would accumulate duplicates;
     `fetch_espn.fetch_draft_picks()` resets the list before each refresh.
   - New DB table `fact_draft_pick` (+ `dim_team` for team names) and
     `docs/data/draft-state.json` (`report.write_draft_state()`), wired into `main.py`.
   - [docs/assistant.html](docs/assistant.html): fully interactive, no backend needed at draft
     time — loads `draft-board.json` + `draft-state.json`, lets you pick "my team", shows
     best-available with need-adjusted VBD (small penalty once a position's starters are filled,
     mirrors `pipeline/draft.py:best_available()`), tracks my roster against `ROSTER_SLOTS`,
     flags positional runs (3+ of one position in the last 5 picks), and accepts manual
     mark-drafted clicks (localStorage-persisted) for picks made since the last pipeline sync —
     merged with the auto-synced list. Verified end-to-end in-browser: team selection, need-adjustment
     kicking in exactly when a position fills, run-alert firing correctly, undo/persistence across
     reload all worked against the real 700-player board.
   - Added `tests/test_fetch_espn.py` and `tests/test_report.py` (duck-typed fake league/pick
     objects — no real espn_api/network needed). 42/42 tests pass.

**Known gaps / next session:**
1. **Draft assistant hasn't been tested against an actual live draft** — the sync timing (how
   fresh `draft-state.json` is depends on when the pipeline last ran) and UX under real time
   pressure are unverified. Consider a tighter-interval `workflow_dispatch` cadence on draft day.
   Discussed two ways to test this without a real draft: (a) an ESPN mock/practice draft if the
   league offers one — **user's preferred approach**, tests the real `mDraftDetail` mid-draft
   behavior we haven't seen yet; (b) synthetic `fact_draft_pick` rows to stress-test the UI at
   full scale. Deferred both for now ("we'll come back to that") — pick up (a) first when ready.
2. `nfl_data_py` endpoints (injuries/snaps/schedule) still 404ing — bye weeks stay blank until
   that resolves; recheck as the season gets closer.
3. Draft date still just "likely later in August" — ask again closer to the time.
4. DST names likely still don't resolve ADP even with the position-fix (Sleeper spells defenses
   by city/team name, ESPN by "X D/ST" — a name-format problem the fuzzy match may not bridge;
   not verified either way).

---

## 2026-08-03 — First real draft board generated; STAT_MAP verified; NaN/JSON bug fixed

Ran `python main.py --mode light` end-to-end against the live league for the first time.

**`evaluate.py`'s `STAT_MAP` is verified, not just guessed** — inspected a real `free_agents()`
payload (Jahmyr Gibbs, Josh Allen). Every key we'd guessed (`passingYards`, `passingTouchdowns`,
`passingInterceptions`, `rushingYards`, `rushingTouchdowns`, `receivingReceptions`,
`receivingYards`, `receivingTouchdowns`, `lostFumbles`, the three `*2PtConversions` keys) matched
ESPN's real `projected_breakdown` exactly. No code change needed — just confidence.

**Real run results:** 703 players (`league.free_agents(size=700)`, since rosters are still empty
pre-draft), 17,304 ESPN projection rows, `validate` all PASS (crosswalk_coverage WARNs — expected,
no one's rostered yet), `health` overall ok. Top of the board (Gibbs, McCaffrey, Nacua, Allen,
Chase...) and ADP-value gaps (Josh Jacobs +11 sleeper, Bijan Robinson −6 reach) look directionally
sane against real 2026 draft discourse.

**Bug found and fixed** ([pipeline/draft.py](pipeline/draft.py)): `players.where(pd.notna(...),
None)` on a float64 column silently recoerces `None` back to `NaN` (pandas has no null for
float64 pre-nullable-dtypes); `json.dump` then wrote the bare `NaN` token — valid for Python's
`json` module, invalid JSON — which broke `JSON.parse` in the browser and blanked the whole draft
board page. Hit this for real: "James Cook III" / "Kenneth Walker III" had no Sleeper ADP match
(suffixed-name mismatch in `transform.resolve_adp`'s exact-name join) so `adp`/`adp_value` were
NaN. Fixed by casting to `object` dtype before the `None` substitution; added
[tests/test_draft.py](tests/test_draft.py) asserting the serialized board never contains a bare
`NaN` token. 33/33 tests pass.

Verified visually in-browser (`docs-static` preview server): board renders, sorts, filters
correctly with the real data.

**Known gaps for next session:**
1. `transform.resolve_adp`'s exact-name match misses suffixed names (`James Cook III` vs however
   Sleeper spells it) — a handful of players show blank ADP. Low priority (renders fine now that
   it's `null`, just incomplete); a fuzzy-match fallback like `crosswalk.py`'s would fix it.
2. `crosswalk.heal` can't resolve anything locally without `nfl_data_py` (not installed — see
   below); harmless pre-draft (crosswalk_coverage only WARNs on rostered players, and there are
   none yet), but will matter once the league drafts and `fetch_nfl` needs to join by `gsis_id`.
3. Bye weeks are all blank locally — needs `fetch_nfl`'s schedule import, same `nfl_data_py`
   blocker.
4. Local full-mode pipeline still needs a 3.11/3.12 venv for `nfl_data_py` (numpy has no cp314
   wheel here); not a CI problem (workflows pin 3.11).
5. Draft date still unknown beyond "likely later in August" — ask again closer to the time.
6. Roster slots beyond §13 defaults deliberately left unconfirmed per user ("assume standard for
   now, we will check when the league is set up again") — note league.settings already gave us
   the *real* counts (bench 5, IR 2) despite that, so this is largely resolved; only worth
   double-checking if the league's settings change before the draft.

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
