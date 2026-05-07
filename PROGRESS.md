# Progress Tracker

## Architecture Overview

**Pipeline:** OpenDota API → Python FastAPI backend (`app/`) → HTML dashboard (`static/dashboard.html`) + Jupyter notebook (`notebook.ipynb`)

**Key files:**
- `app/main.py` — FastAPI entry, registers routers
- `app/client.py` — async httpx OpenDota wrapper (singleton)
- `app/models.py` — Pydantic v2 models
- `app/routes/` — players.py, matches.py, friends.py, dashboard.py, analytics.py
- `app/collector.py` — async data collector for probability model inputs
- `app/match_cache.py` — two-level match history cache (shared by CLI + notebook)
- `cli.py` — Typer CLI: serve / add / remove / list / refresh-data / refresh-matches
- `friends.json` — 7 tracked players (32-bit account_id + 64-bit steam_id_64 + label)
- `notebook.ipynb` — 14-section exploration notebook
- `static/dashboard.html` — dark-theme dashboard (Tier 1 + Tier 2 complete)

**Tracked players (7):**

| Label   | account_id | steam_id_64         |
|---------|------------|---------------------|
| Sherry  | 185602862  | 76561198145868590   |
| Haseeb  | 105774679  | 76561198066040407   |
| Abidi   | 97129625   | 76561198057395353   |
| Rafay   | 135953784  | 76561198096219512   |
| ABT     | 124437009  | 76561198084674737   |
| Cancer  | 104794975  | 76561198065060703   |
| Zain    | 90972450   | 76561198051238178   |

**OpenDota API limits:** 60 req/min free tier. All fetch loops use `CALL_DELAY = 1.05s` (~57 req/min).

---

## Done

### Repo scaffold
- [x] FastAPI app, async OpenDota client, Pydantic models
- [x] Routes: `/players`, `/matches`, `/friends`, `/dashboard`, `/heroes/reference`, `/analytics`
- [x] CLI (`cli.py`) — serve / add / remove / list / **refresh-data** / **refresh-matches**
- [x] `friends.json` — 7 players (5 original + Cancer 104794975 + Zain 90972450)
- [x] `project_primer.md` written
- [x] `requirements.txt` includes `pyarrow>=14.0` (for parquet writes in §13)

### Tier 1 dashboard (complete)
- [x] `FriendSummary` extended: label, avg_kda, avg_gpm, avg_xpm, recent_form, current_streak
- [x] Dashboard route computes all Tier 1 stats
- [x] `static/dashboard.html` — dark-theme dashboard: friend cards, detail panel (heroes + matches + KDA trend), group comparison charts (winrate, KDA, GPM/XPM), group synergy panel

### Tier 2 — Step A (complete — zero extra API calls)
- [x] `app/client.py` extended: `get_matches_by_role`, `get_hero_matchups`, `get_hero_stats_global`
- [x] `FriendSummary` extended: avg_hero_damage_per_min, avg_last_hits_per_min, avg_tower_damage, kda_std, gpm_std, hero_pool_size, role_stats, duration_stats
- [x] Dashboard route computes all Tier 2 stats from recentMatches
- [x] `dashboard.html` updated: Tier 2 stat row on cards (DMG/m, LH/m, Pool), detail panel role performance + duration buckets + consistency panel, hero damage chart, **role performance heatmap** (all players × all roles)

### Data layer for probability model (complete)
- [x] `app/collector.py` — async data collector; saves `player_role_stats.json`, `hero_matchups.json`, `hero_global_stats.json` to `data/`
- [x] `app/routes/analytics.py` — `/analytics/player-role-stats`, `/analytics/hero-matchups`, `/analytics/hero-global-stats`, `POST /analytics/refresh`
- [x] `python cli.py refresh-data [--force]` — triggers full collection (~50 API calls, cached for 6 h)

### Match cache layer (complete)
- [x] `app/match_cache.py` — shared async caching module
  - `collect_match_history(account_ids, limit, force)` — Phase 1 (match ID lists) + Phase 2 (full match JSON)
  - `load_player_match_list(account_id)` → `list[dict]`
  - `load_match(match_id)` → `dict | None`
  - `extract_player_stats(match, account_id)` → flat stats dict (25 fields incl. kda, dmg_per_min, lh_per_min)
  - All I/O uses `encoding='utf-8'` (Windows cp1252 fix)
  - `CALL_DELAY = 1.05s` (57 req/min, under 60 req/min free cap)
- [x] `data/match_cache/player_match_ids/{id}.json` — per-player match list (200 entries each)
- [x] `data/match_cache/matches/{match_id}.json` — full match JSON (permanent, never re-fetched)
- [x] `python cli.py refresh-matches [--limit 200] [--force]` — CLI trigger
- [x] `.gitignore` updated: `data/match_cache/` and `notebook_cache/` excluded

### Notebook — 14 sections (complete structure)
- [x] §1: Setup & imports
- [x] §2: Load player data into `D` dict (account_id → player data from OpenDota)
- [x] **§2b**: Deep match cache — fetches 200 matches/player into `data/match_cache/`, builds `DEEP` dict (`dict[int, list[dict]]`)
- [x] §3–§12: Various analyses (heroes, roles, matchups, etc.)
- [x] **§13**: Differential (marginal WR) analysis:
  - Computes `baselines` dict (career WR per player from `/players/{id}`)
  - **Part 1 (Player×Player)**: from `/peers` career data (≥5 games); heatmap + `diff_player_x_player.parquet`
  - **Part 2 (Player×Role)**: uses `DEEP` if §2b has run (200 matches, ≥3 games), else `d['recent'][:20]` (≥2 games); heatmap with game-count overlay + `diff_player_x_role.parquet`
  - **Part 3 (Player×Hero)**: from career `/heroes` stats (≥5 games); 2×4 grid of per-player top-5 hero lift bar charts + `diff_player_x_hero.parquet`
  - Diverging colormap centered at 0 (`sns.diverging_palette(10, 130)`)
  - Graceful degradation: `try: _deep_available = bool(DEEP) except NameError: _deep_available = False`

---

## In Progress / Immediate Next Steps

1. **Re-run notebook §2** — needed to load Cancer (104794975) and Zain (90972450) into `D`. These two players were added after the last §2 run; the notebook cache (`notebook_cache/`) still has only 5 players.

2. **Run `python cli.py refresh-data`** (or `POST /analytics/refresh`) — populates `data/player_role_stats.json`, `data/hero_matchups.json`, `data/hero_global_stats.json` for the first time with all 7 players. (~50 API calls, ~2–3 min.)

3. **Re-run notebook §2b** — the match cache fetch was interrupted after successfully fetching all 7 players' match ID lists, but encoding errors prevented 7 full-match files from being written. Both bugs are now fixed (encoding + rate limit). Re-running will:
   - Skip Phase 1 (match ID lists already cached for all 7 players)
   - Retry the 7 previously failed matches + fetch all remaining ~793 uncached full matches
   - Estimated time: ~14 min at 57 req/min
   - After completion, re-run §13 Part 2 to use the full `DEEP` dataset (200 matches/player vs 20)

4. **Install pyarrow** if not yet done: `pip install pyarrow` — required for §13 parquet writes.

---

## Backlog

### Tier 2 — Step B (requires 200-match cache — unblocked once §2b completes)
- [ ] Longest all-time win/loss streak
- [ ] Rolling 7-day winrate trend (improvement over time)

### Tier 3 — Social stats
- [ ] Head-to-head match history cross-reference (shared match IDs)
- [ ] Best teammate metric (friends who most improve your WR)

### Tier 4 — Advanced
- [ ] Hero percentile display on dashboard (from `/rankings` — already fetched)
- [ ] Ward score, buyback rate, comeback/stomp index (requires full per-match fetch — already cached)

### Win Probability Model (Layer 1)
- [ ] Build `app/routes/probability.py` using cached data:
  - hero matchup advantage (from `hero_matchups.json`)
  - player skill on hero (from per-player hero stats)
  - role fit score (from `player_role_stats.json`)
  - global baseline (from `hero_global_stats.json`)

### Dashboard
- [ ] Hero portrait images (OpenDota CDN)
- [ ] Match detail modal (click a match row → full breakdown)
- [ ] Probability model UI (hero draft inputs → win % output)
- [ ] Add Cancer and Zain cards (dashboard currently shows 5 players; friends.json now has 7)

---

## Known Issues / Notes

- `mmr_estimate` is null for most players — rank badge uses `rank_tier` only
- `/players/{id}/matches` (paginated) drops `lane_role` — role analysis limited to last 20 recentMatches unless `DEEP` cache is used
- Career `/totals` has inconsistent `n` — detailed fields (stuns, wards, APM) only parsed for ~800 of 4800+ matches
- `obs_placed` (wards) only in full per-match fetch, not recentMatches — available in `DEEP`
- `refresh-data` makes ~50 API calls (5 roles × 7 players + ~20 hero matchups + 1 global); runs in ~2–3 min at 1.05 s/call spacing
- Windows encoding: all `Path.read_text()` / `write_text()` calls must use `encoding='utf-8'` — system default (cp1252) cannot encode Cyrillic player names in match JSON
- Parquet dependency: `pyarrow>=14.0` required for `df.to_parquet()` — not installed by default

## File Size Estimates

- `data/match_cache/player_match_ids/` — ~7 files × ~30 KB = ~210 KB
- `data/match_cache/matches/` — ~800 files × ~200 KB = ~160 MB (excluded from git)
- `data/diff_player_x_player.parquet` — ~KB (7×7 matrix)
- `data/diff_player_x_role.parquet` — ~KB (7×5 matrix)
- `data/diff_player_x_hero.parquet` — ~KB (7 × N heroes)
