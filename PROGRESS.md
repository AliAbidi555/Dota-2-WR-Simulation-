# Progress Tracker

## Done
- [x] Initial repo scaffold — FastAPI app, async OpenDota client, Pydantic models
- [x] Routes: `/players`, `/matches`, `/friends`, `/dashboard`, `/heroes/reference`, `/analytics`
- [x] CLI (`cli.py`) — serve / add / remove / list / **refresh-data**
- [x] `friends.json` populated with 5 players (64-bit Steam IDs converted to 32-bit account IDs)
- [x] `project_primer.md` written

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

### Notebook (complete)
- [x] `notebook.ipynb` — 14 sections: §1–12 as before + **§2b: deep match cache (200 matches/player → `data/match_cache/`)** + **§13: differential analysis (marginal WR by teammate / role / hero → 3 parquet files; role section uses DEEP when §2b has run)**

### Match cache layer (complete)
- [x] `app/match_cache.py` — shared async caching: `collect_match_history`, `load_match`, `extract_player_stats`
- [x] `data/match_cache/player_match_ids/{id}.json` — per-player match list (200 entries)
- [x] `data/match_cache/matches/{match_id}.json` — full match JSON (permanent, never re-fetched)
- [x] `python cli.py refresh-matches [--limit 200] [--force]` — CLI trigger
- [x] `.gitignore` updated: `data/match_cache/` and `notebook_cache/` excluded

## In Progress
- [ ] Run `python cli.py refresh-data` to populate analytics `data/` cache for the first time
- [ ] Re-run §2 in notebook to load Cancer (104794975) and Zain (90972450) into `D`
- [ ] Run `python cli.py refresh-matches` (or notebook §2b) to populate `data/match_cache/` (~5 min first run)

## Backlog

### Tier 2 — Step B (requires paginated /matches, ~1–2 extra calls/player)
- [ ] Longest all-time win/loss streak (needs 200+ matches per player)
- [ ] Rolling 7-day winrate trend (improvement over time)

### Tier 3 — Social stats
- [ ] Head-to-head match history cross-reference (shared match IDs)
- [ ] Best teammate metric (friends who most improve your WR)

### Tier 4 — Advanced
- [ ] Hero percentile display on dashboard (from /rankings — already fetched)
- [ ] Ward score, buyback rate, comeback/stomp index (requires full per-match fetch + cache)

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

## Known Issues / Notes
- `mmr_estimate` is null for most players — rank badge uses `rank_tier` only
- `/players/{id}/matches` (paginated) drops `lane_role` — role analysis limited to last 20 recentMatches
- Career `/totals` has inconsistent `n` — detailed fields (stuns, wards, APM) only parsed for ~800 of 4800+ matches
- `obs_placed` (wards) only in full per-match fetch, not recentMatches
- `refresh-data` makes ~50 API calls (5 roles × 5 players + ~20 hero matchups + 1 global); runs in ~2–3 min at 0.3 s/call spacing
