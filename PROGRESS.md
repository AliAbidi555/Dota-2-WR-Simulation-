# Progress Tracker

## Done
- [x] Initial repo scaffold — FastAPI app, async OpenDota client, Pydantic models
- [x] Routes: `/players`, `/matches`, `/friends`, `/dashboard`
- [x] CLI (`cli.py`) — serve / add / remove / list
- [x] `friends.json` populated with 5 players (64-bit Steam IDs converted to 32-bit account IDs)
- [x] `project_primer.md` written
- [x] `app/routes/heroes.py` — `/heroes/reference` endpoint (hero id → localized name)
- [x] `FriendSummary` model extended: `label`, `avg_kda`, `avg_gpm`, `avg_xpm`, `recent_form`, `current_streak`
- [x] Dashboard route updated to compute all Tier 1 stats (avg KDA/GPM/XPM, form sequence, streak)
- [x] `app/main.py` updated: static file mount + `/heroes/reference` router + root serves `dashboard.html`
- [x] `static/dashboard.html` — Tier 1 dark-theme dashboard (cards, detail panel, Chart.js group charts, group synergy panel)
- [x] `notebook.ipynb` — all 9 sections: setup, data fetching, winrate overview, KDA trend, hero heatmap, GPM/XPM scatter, recent form sparklines, group synergy matrix, pipeline diagram
- [x] `requirements.txt` updated with notebook dependencies (pandas, matplotlib, seaborn, numpy, jupyter)

## In Progress
- [ ] Install dependencies in project venv: `pip install -r requirements.txt`

## Backlog
- [ ] Tier 2 stats: hero damage/min, LH/min, win/loss streaks (all-time), perf by game duration, perf by role/lane, hero pool diversity
- [ ] Tier 3 stats: head-to-head match history cross-reference, best teammate metric
- [ ] Tier 4 stats: hero percentile, improvement trend (rolling 7-day WR), ward score, comeback index
- [ ] Dashboard: hero portrait images (OpenDota CDN)
- [ ] Dashboard: match detail modal (click a row → full match breakdown)
- [ ] Win probability model (Layer 1: hero matchup + player skill + role fit + synergy)
- [ ] Patch-aware stat filtering (`version` field on matches)
- [ ] Time-of-day performance analysis

## Known Issues / Notes
- `mmr_estimate` is null for most players — rank badge uses `rank_tier` only
- `/players/{id}/matches` (paginated) drops `lane` / `lane_role` / `is_roaming` — role analysis limited to last 20 recentMatches
- Career totals (`/totals`) have inconsistent `n` — detailed fields (stuns, wards, APM) only parsed for ~800 of 4800+ matches
- `obs_placed` (wards) only available in full per-match fetch, not recentMatches
- OpenDota free tier: ~50k calls/month without API key; set `OPENDOTA_API_KEY` in `.env` for higher limits
- VS Code may show "package not installed" hints — run `pip install -r requirements.txt` in the project venv
