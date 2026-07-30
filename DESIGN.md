# Fantasy Football Dashboard — Design, Architecture & Build Reference

> Seed document for a new **Fantasy Football** analytics dashboard + draft tool, modeled on the
> "Pitch Slap" fantasy baseball project but rebuilt for football's points-based, draft-centric,
> weekly game. **This file is intentionally self-contained** — it carries the concrete
> architecture, reliability recipes, ESPN specifics, and valuation math needed to scaffold and
> build the project *without* referring back to the baseball repo. (Reach back only if truly needed.)
>
> Copy into a fresh `Fantasy-Football` repo as the starting DESIGN/PLANNING doc.
> Status: **Phase 0 + Phase 1 scaffolded** (2026-07-30) — repo structure, pipeline spine, and
> draft-board valuation/UI are in place per §14. Blocked on the §12 open questions (league ID,
> roster/teams, confirmed scoring) before the board produces real numbers. See
> [PLANNING.md](PLANNING.md) for the running build log. Created 2026-07-30.

---

## 1. Goal

A self-hosted, reliability-hardened dashboard — static site on **GitHub Pages**, fed by JSON from
a **scheduled GitHub Actions pipeline** — that helps with **both**:
- **The draft** (pre-season): rankings, tiers, value-based drafting (VBD), ADP value, live draft assistant.
- **The season** (weekly): start/sit, waivers, matchup analysis, trades, playoff prep.

Principles (inherited from Pitch Slap): tailored to *my* league, transparent logic, **self-monitoring**,
low-maintenance, no paid infra.

---

## 2. Decisions locked (2026-07-30)

| Decision | Value | Implication |
|---|---|---|
| Platform | **ESPN** | Reuse `espn_api` (Python) integration + cookie auth. |
| League type | **Redraft** | Season-long value only — no dynasty age-curves/rookies/picks. |
| Draft format | **Snake** | Valuation = rankings/tiers/VBD + ADP value at pick. (Auction = $-value model, out of scope v1.) |
| Scoring | **TBD → default half-PPR** | Apply scoring as a config-driven multiplier over projected stat lines. |

---

## 3. The conceptual shift: baseball (categories) → football (points + draft)

Pitch Slap is **category rotisserie** (cat-states, need-weights, swing categories). Football differs fundamentally:
- **Points, not categories** → valuation = **projected points + positional value (VBD/VORP)**. The scoring/evaluate brain is new.
- **The draft is a first-class subsystem** — the marquee pre-season deliverable; baseball had none.
- **Cadence flips** — weekly (~17-wk season), but with a decisive **Sunday-AM inactives/injury** window.
- **New signals** — Vegas lines (implied team totals, spreads), injury tags (Q/D/O), snap %, target share, defense-vs-position (DvP), **bye weeks**.
- **What carries over unchanged:** the whole reliability spine (§7–8).

---

## 4. Tech stack & repo layout

**Stack:** Python 3.11 · SQLite (local ephemeral DB, rebuilt each CI run) · `espn_api` · `nfl-data-py`
(nflverse) · `requests` · `pandas` · `rapidfuzz` (crosswalk) · pytest · GitHub Actions · GitHub Pages.

```
config.py                 # league settings + scoring + ESPN IDs; snapshots to config_history/
config_history/           # timestamped config.py snapshots (snapshot before every change)
espn_credentials.py       # ESPN_SWID / ESPN_S2 cookies — GITIGNORED; written from secrets in CI
pipeline/
  init_db.py              # SQLite schema + seed_crosswalk() (seed dim_players from committed CSV if empty)
  fetch_espn.py           # league, rosters, matchups, settings, ESPN projections (via espn_api)
  fetch_projections.py    # external projections/ADP (Sleeper ADP, optional FantasyPros)
  fetch_nfl.py            # schedule, byes, injuries, snaps, targets, Vegas lines (nfl-data-py + Odds API)
  crosswalk.py            # build + self-heal ESPN-ID <-> nflverse/gsis-ID mapping
  transform.py            # joins on player_id; weekly + season views
  validate.py             # integrity checks; FAIL -> sys.exit(1) blocks the run
  evaluate.py             # projected points, VBD/VOR, start/sit, waiver value, matchup difficulty
  draft.py                # draft board (tiers/VBD/ADP) + live best-available assistant
  report.py               # writes docs/data/*.json + CSVs
  health.py               # output-completeness checks -> docs/data/health.json
main.py                   # orchestrator: --mode full|light ; runs phases; non-fatal health at end
data/                     # player-crosswalk.csv (committed seed), crosswalk-overrides.json (committed),
                          #   transient *.json (gitignored, regenerated each run)
docs/                     # GitHub Pages root
  index.html, draft.html, assistant.html, startsit.html, waivers.html, matchup.html,
  trades.html, playoff.html, log.html
  data/*.json             # committed by CI each run; the site fetches these
tests/                    # pytest: import smoke, config invariants, evaluate/health/draft logic
.github/workflows/
  pipeline.yml            # cron + workflow_dispatch; runs main.py; commits docs/data; health gate
  tests.yml               # on code pushes/PRs (paths-ignore docs/data + data)
requirements.txt          # runtime deps
requirements-dev.txt      # -r requirements.txt + pytest
CLAUDE.md                 # AI session guardrails (boundaries, no-touch list, small diffs)
PLANNING.md               # running build log — update every session
DESIGN.md                 # this file
```

---

## 5. Architecture — two modes, one pipeline spine

**Shared pipeline (main.py phases):**
```
fetch_espn        → league, rosters, matchups, settings, ESPN projections
fetch_projections → external projections + ADP (Sleeper), optional consensus
fetch_nfl         → schedule, byes, injuries, snaps, targets, Vegas
crosswalk.heal    → resolve any rostered/relevant player missing an ID (self-heal; non-fatal)
transform         → join on player_id; weekly + season views
validate          → integrity checks (FAIL blocks the run)
evaluate          → projected points, VBD/VOR, start/sit, waiver/matchup/trade value
report            → docs/data/*.json
health            → output-completeness -> health.json (non-fatal; workflow alerts)
```

**Pre-season / DRAFT mode**
- `draft_board`: rankings + **tiers** (gap-based) + **VBD/VOR by position** (replacement level from
  roster × #teams) + **ADP value** (sleeper/reach) + positional scarcity + **bye clustering**.
- `draft_assistant` (live): mark players drafted → **best available given my roster + positional
  need + bye conflicts + ADP value**; positional-run alerts.
  *(Unknown: does ESPN expose live draft picks via API for auto-sync, or is manual mark-drafted required? → research.)*

**In-season / SEASON mode (weekly)**
- Start/sit optimizer · Waivers (opportunity: snaps/targets/role change) · Matchup (Vegas + DvP) ·
  Trade analyzer (reuse lineup-aware/multi-layer value) · Playoff prep (playoff-week schedule strength).

**Dashboard pages:** Draft Board · Draft Assistant · Start/Sit · Waivers · Matchup · Trades · Playoffs · Log/Health.
Static HTML that `fetch()`es `docs/data/*.json`; dark theme; `?` tooltip pattern; health banner on Home.

---

## 6. Football valuation math (the new brain)

### 6.1 Projected points
Apply league scoring to a projected stat line. Config-driven (default half-PPR):
```
pass_yds*0.04 + pass_td*4(or 6) + int*(-2)
+ rush_yds*0.10 + rush_td*6
+ rec*PPR(0/0.5/1) + rec_yds*0.10 + rec_td*6
+ fumbles_lost*(-2) + 2pt*2 ...  (K and DST have their own scoring)
```

### 6.2 VBD / VOR (core draft valuation)
`player_value = projected_season_points − replacement_points(position)`
- **Replacement level** = the points of the *Nth* player at a position, where N ≈ the number of
  that position started across the whole league. Rule of thumb: `N_pos = teams × (starters_at_pos +
  FLEX_share)`. FLEX demand is split across RB/WR/TE by how often each fills it (tune, e.g. RB/WR heavy).
- VBD makes cross-position value comparable (a RB and a WR with the same VBD are equally valuable to draft).

### 6.3 Tiers (gap-based)
Within a position, sort by VBD desc; start a new tier when the gap to the next player exceeds a
threshold (e.g. > ~0.75× the local average gap, or a fixed points gap). Tiers matter more than exact
rank on draft day (draft the last player in a tier before it breaks).

### 6.4 ADP value (sleeper / reach)
Compare a player's **VBD rank** to his **ADP**. Available *later* than his value → sleeper/target;
going *earlier* than his value → reach/fade. Surface the biggest positive gaps as draft targets.

### 6.5 Positional scarcity
Steepness of the VBD dropoff by position (and tier thinness) → informs when to prioritize a position
before a run. Bye-week clustering: avoid stacking too many starters on the same bye.

### 6.6 In-season start/sit & waiver value
`weekly_value = weekly_projected_points × matchup_adj × availability`
- `matchup_adj` from Vegas (team implied total, game spread/total) + defense-vs-position rank.
- `availability` from injury tag / inactive status (0 if OUT/inactive).
- **Waiver opportunity** = change in role/usage: snap %↑, target share↑, vacated touches (injury ahead
  on depth chart), red-zone usage — often more predictive than last week's points.

---

## 7. Reliability playbook — CONCRETE recipes (hard-won on Pitch Slap 2026)

Bake these in from day 1. Each cost a real debugging arc to learn.

### 7.1 Data-derived state, never date math
Pitch Slap silently shipped a broken page for **16 days** because "current week" was `2 + days//7`
date math that drifted at a schedule break. **Rule: derive "current week" (and any period) from the
platform's own data** (ESPN's current matchup / scoring period), not the calendar.

### 7.2 Player-ID crosswalk + daily self-heal
- Committed seed: `data/player-crosswalk.csv` (ESPN player_id ↔ external stat IDs) + manual
  `data/crosswalk-overrides.json` (`{espn_id: {mlb_id/gsis_id, note}}` for ambiguous names).
- `init_db.seed_crosswalk()` loads the CSV into `dim_players` if the table is empty (CI starts fresh).
- **`crosswalk.heal()`** runs right after fetch each run: find rostered/relevant players missing an ID;
  resolve via overrides → exact name → unique fuzzy (rapidfuzz); **upsert `dim_players` + append the
  CSV** (so the seed self-improves); anything still ambiguous is returned as `unresolved` and logged.
  **Non-fatal** — validate remains the gate. This stops roster churn / call-ups from blocking runs.

### 7.3 Two-tier checking: `validate` (blocking) + `health` (completeness, alerting)
- **`validate`** = data *integrity*. Each check returns `{check, status: pass|warn|fail, detail}`;
  `run()` writes `docs/data/validation-report.json`; **any FAIL → `sys.exit(1)`** (blocks the run,
  don't publish garbage). WARN is non-blocking.
- **`health`** = output *completeness* — catches *silent degradation* (a run that "succeeds" but ships
  an incomplete page). `health.run(db_path, write=True) -> {overall: ok|degraded, degraded_checks:[],
  checks:[{check,status,detail}]}`, writes `docs/data/health.json`. `__main__` does
  `run(write=False); sys.exit(1 if degraded)`. Checks target real failure modes: expected output files
  present & non-empty, key section populated (not all-blank), stats fresh, row counts sane, projections
  present. Wire into `main.py` at the end (non-fatal via try/except).

### 7.4 Commit-then-email alerting (never lose data, still get told)
Workflow order: run pipeline → **commit + push `docs/data`** → then a final step re-runs health and
**exits 1 iff degraded**, turning the job red so **GitHub emails you** — *after* the data is already
published. So a degraded run still updates the site AND alerts same-day.
```yaml
# .github/workflows/pipeline.yml (essentials)
on:
  schedule: [{cron: '0 12 * * 2,3'}]   # Tue/Wed; add a Sunday-AM cron in-season
  workflow_dispatch:
jobs:
  run:
    runs-on: ubuntu-latest
    permissions: { contents: write }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11', cache: pip }
      - run: pip install -r requirements.txt
      - name: Write ESPN creds
        env: { ESPN_SWID: ${{ secrets.ESPN_SWID }}, ESPN_S2: ${{ secrets.ESPN_S2 }} }
        run: printf 'ESPN_SWID="%s"\nESPN_S2="%s"\n' "$ESPN_SWID" "$ESPN_S2" > espn_credentials.py
      - run: python -m pipeline.init_db
      - run: python main.py --mode full
      - name: Commit data
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/data/ data/player-crosswalk.csv
          git diff --staged --quiet || git commit -m "data: run $(date -u +'%Y-%m-%d %H:%M UTC')"
          git push
      - name: Alert on degraded output      # data already pushed above
        run: python -m pipeline.health
```

### 7.5 Graceful degradation on external-API breaks
Wrap every flaky fetch (scrapers, third-party APIs) in try/except; on failure **preserve the last good
DB data** and return `skipped` with a warning, rather than crashing the whole run. (Football: Vegas/odds
and projection scrapers are the likely flaky ones.)

### 7.6 Ground-truth checks
Cross-check computed stats against the platform's own numbers (ESPN exposes actual + projected stat
breakdowns per player — see §9). Compare per-player; **WARN-only** on systematic drift (> ~10% of
values beyond tolerance); PASS otherwise. **Calibrate tolerances against *same-day* data** — a stale
local DB will show huge false divergence (learned the hard way: 0.31 vs 0.003 once refreshed).

### 7.7 Config + guardrails + tests
- `config.py` holds league settings + scoring; **snapshot to `config_history/` before every change**.
- Credentials: `try: from espn_credentials import ESPN_SWID, ESPN_S2 except ImportError: ESPN_SWID=ESPN_S2=None`
  so the code imports without secrets (tests/local).
- **CLAUDE.md**: boundary/no-touch list (workflow, schema, CSV columns, validate checks — add never
  weaken), small diffs, update PLANNING every session, don't force-push main.
- **tests/ + tests.yml**: import smoke (all modules import creds-free), config invariants (no date-math
  landmines), evaluate/health/draft logic. Run on code pushes; path-ignore `docs/data/**` + `data/**`
  so the data-commit bot doesn't trigger them.
- **Don't commit locally-regenerated data** — the scheduled cloud run is the source of truth for the
  live site; local runs are for preview/test only.

---

## 8. Data sources (football)

| Need | Source | Notes |
|---|---|---|
| League / rosters / matchups / settings / ESPN projections | **ESPN** via `espn_api` | Same library family as baseball. |
| ADP | **Sleeper** public API (no auth) + ESPN | Free, clean. |
| Rankings / consensus (optional upgrade) | FantasyPros ECR | Better than single-source; subscription/scrape. |
| Stats / advanced (in-season) | **`nfl-data-py`** (nflverse) | Free: snaps, targets, air yards, EPA, usage, weekly stats. |
| Injuries | ESPN status + nflverse | Sunday-AM inactives are decisive. |
| Vegas lines | The Odds API (free tier) or scrape | Implied team totals + spreads. |

Make projection/ranking/ADP **pluggable sources** so upgrades (e.g. FantasyPros) don't touch valuation.

---

## 9. ESPN / espn_api specifics that transfer

- **Auth:** ESPN private-league cookies `SWID` + `espn_s2`. Store in gitignored `espn_credentials.py`;
  write from GitHub secrets in CI. `League(league_id, year, espn_s2, swid)`.
- **Player stat structure:** `player.stats` is keyed by scoring-period id; **period `0` = season**.
  Each entry has `breakdown` (actual) and `projected_breakdown` (projection), keyed by stat abbrev.
  (In baseball this powered both projections and the ground-truth check. Football will have football
  stat abbrevs — inspect once and map.)
- **Gotcha:** ESPN stat/period ids are easy to confuse (period id ≠ stat-category id). Inspect the live
  payload and map explicitly; guard `float()` coercions (some fields come back as dicts/containers).
- **Week detection:** read ESPN's current matchup/scoring period from the API — **not** from a date.
- **Live draft:** unknown whether espn_api / the ESPN endpoints expose live pick order during a draft.
  Research early; design the assistant to accept a manual "mark drafted" input as fallback.

---

## 10. Cadence / workflow

- **Pre-season:** daily-ish refresh (rankings/ADP/projections move through camp/preseason).
- **In-season:** main run **Tue/Wed** (post-MNF, post-waivers) + **Sunday-AM** refresh (~2h pre-slate)
  for final inactives/injury before lineup lock. `workflow_dispatch` for draft-day/manual runs.
- Commit `docs/` each run → GitHub Pages serves the site. (Enable Pages: Settings → Pages → main/docs.)

---

## 11. Phased roadmap (draft-first — the clock is the constraint)

- **Phase 0 — Shared spine:** repo scaffold, config + snapshots, ESPN football fetch, crosswalk +
  self-heal, validate/health/CI skeleton, dashboard shell, CLAUDE.md.
- **Phase 1 — Draft board (PRIORITY, before draft day):** projections + ADP + rankings → VBD/VOR,
  tiers, scarcity, bye clustering, ADP value; sortable board page with "fills my need" highlighting.
- **Phase 2 — Live draft assistant:** draft-state input (ESPN live API research; manual fallback) →
  best-available given roster/needs/byes/value; positional-run alerts.
- **Phase 3 — In-season dashboard:** weekly pipeline (Tue/Wed + Sun-AM), start/sit, waivers, matchup,
  trades, playoff prep, full health/alert/test layer.

---

## 12. Open questions — backlog

**Blocks accurate draft board (Phase 1):**
1. **Roster slots** — QB (1 or superflex/2QB?), RB/WR/TE/**FLEX** counts, K & DST?, bench + IR size.
2. **# of teams** (8/10/12/14?) — sets replacement levels & scarcity.
3. **Draft date** — runway.

**Quality / scope:**
4. **Projection source** — ESPN-only (free/easy) vs add FantasyPros consensus (better; paid/scrape) vs
   blend. *Recommendation: ESPN + Sleeper ADP for v1, pluggable.*
5. **Scoring specifics** — confirm half-PPR; TE-premium? 6-pt pass TD? yardage/other bonuses?

**Phase 2 research:**
6. Does ESPN expose **live draft picks** via API (auto-sync) or is manual mark-drafted required?

**Later / in-season:**
7. Waiver type (FAAB vs priority) + budget, trade deadline, playoff weeks/teams, IR rules.
8. Vegas data source (Odds API key vs scrape).

---

## 13. Recommended starting defaults (refine when answers land)

- **12-team**, **half-PPR**, starters **1 QB / 2 RB / 2 WR / 1 TE / 1 FLEX / 1 K / 1 DST**, bench ~7, 1 IR.
- Projections **ESPN**; ADP **Sleeper**; advanced stats **nfl-data-py**; Vegas via Odds API.
- Everything config-driven so real settings slot in without rework.

---

## 14. Next step

Scaffold **Phase 0 + Phase 1** with the defaults above (draft clock is the constraint); refine the
moment roster / #teams / draft date / scoring are confirmed. Phase 2 after the board is usable; Phase 3
after the draft. When starting the new repo, drop this file in as `DESIGN.md`, create `PLANNING.md`
(running log) and `CLAUDE.md` (guardrails) alongside it, then begin Phase 0.
