# Dota 2 Performance Tracker — Project Primer

> **For the Codex agent reading this file:** This document is your complete context for the project. Read it fully before making any changes. Maintain the progress tracker in `PROGRESS.md` and the exploration notebook in `notebook.ipynb` as you work.

---

## Project Goal

Build an **HTML performance dashboard** that lets a group of friends track their Dota 2 game history and statistics using the free [OpenDota REST API](https://docs.opendota.com/). The dashboard must be self-contained (single HTML file or a small static site) and pull live data from the Python API backend on load.

The pipeline is:

```
OpenDota API → Python FastAPI backend → HTML dashboard (front-end)
               (app/)                    (dashboard.html or /static)
```

---

## Repo Layout

```
Dota 2 tracker/
├── app/
│   ├── main.py          ← FastAPI entry point; registers all routers
│   ├── config.py        ← Pydantic-settings; reads .env
│   ├── client.py        ← Async httpx wrapper for OpenDota (singleton)
│   ├── models.py        ← Pydantic request/response models
│   └── routes/
│       ├── players.py   ← /players/{id} endpoints
│       ├── matches.py   ← /matches/{id}
│       ├── friends.py   ← /friends CRUD (reads/writes friends.json)
│       └── dashboard.py ← /dashboard — aggregates all friends in parallel
├── cli.py               ← Typer CLI: serve / add / remove / list
├── friends.json         ← Source of truth for tracked players (see below)
├── notebook.ipynb       ← ⚠ YOU MUST MAINTAIN THIS (see §Notebook)
├── PROGRESS.md          ← ⚠ YOU MUST MAINTAIN THIS (see §Progress Tracker)
├── requirements.txt
├── .env / .env.example
└── project_primer.md    ← This file
```

---

## Friends List

Tracked players are stored in `friends.json`. The schema for each entry is:

```json
{
  "friends": [
    {
      "account_id": 185602862,
      "label": "Sherry",
      "steam_id_64": 76561198145868590
    }
  ]
}
```

**Key facts:**
- `account_id` is the **32-bit OpenDota ID** (= `steam_id_64 - 76561197960265728`). This is what every OpenDota endpoint uses.
- `steam_id_64` is stored for reference only (not used by the API client).
- `label` is a human-readable nickname shown in the UI.

Current friends:

| Label   | account_id  | steam_id_64         |
|---------|-------------|---------------------|
| Sherry  | 185602862   | 76561198145868590   |
| Haseeb  | 105774679   | 76561198066040407   |
| Abidi   | 97129625    | 76561198057395353   |
| Rafay   | 135953784   | 76561198096219512   |
| ABT     | 124437009   | 76561198084702737   |

---

## OpenDota API Reference (endpoints used)

All calls go to `https://api.opendota.com/api`. No auth required; optional `?api_key=` for higher rate limits (~50k free calls/month without key).

| Endpoint | Returns |
|----------|---------|
| `GET /players/{id}` | Profile: `rank_tier`, `mmr_estimate`, Steam name, avatar |
| `GET /players/{id}/wl` | `{ win, lose }` totals |
| `GET /players/{id}/recentMatches` | Last 20 matches (fast, cached) |
| `GET /players/{id}/matches?limit=N` | Paginated match history |
| `GET /players/{id}/heroes` | Per-hero: `games`, `win`, KDA breakdown |
| `GET /players/{id}/peers` | Most frequent teammates |
| `GET /players/{id}/totals` | Career totals (kills, gold, XP…) |
| `GET /players/{id}/rankings` | Hero percentile vs. all OpenDota players |
| `GET /matches/{match_id}` | Full match: all 10 players, items, wards, objectives |
| `GET /heroes` | Reference: hero_id → name, roles, primary_attr |

`rank_tier` decoding: tens digit = medal (1=Herald … 8=Immortal), units digit = stars (1–5).

---

## Statistics to Implement

Below are all statistics that are feasible with OpenDota data, grouped by priority. Implement them in order.

### Tier 1 — Core (implement first)

| Stat | Description | Source endpoint |
|------|-------------|-----------------|
| **Overall winrate** | Wins / (Wins + Losses) × 100 | `/players/{id}/wl` |
| **KDA** | (Kills + Assists) / max(Deaths, 1) | `/recentMatches` |
| **GPM / XPM** | Gold & XP per minute averages | `/recentMatches` |
| **Recent form** | Win/loss sequence for last 10 games | `/recentMatches` |
| **Top 5 heroes** | Most played + winrate per hero | `/players/{id}/heroes` |
| **Rank badge** | Medal + stars from `rank_tier` | `/players/{id}` |

### Tier 2 — Performance Depth

| Stat | Description | Source endpoint |
|------|-------------|-----------------|
| **Hero damage per min** | Average `hero_damage / duration` | `/recentMatches` |
| **Last hits per min** | `last_hits / duration` | `/recentMatches` |
| **Win streak / loss streak** | Current streak from recent matches | `/recentMatches` |
| **Performance by game duration** | Winrate in <30 min, 30–45 min, >45 min | `/players/{id}/matches` |
| **Performance by role/lane** | Winrate as carry / support / offlane | `/players/{id}/matches` |
| **Longest win/loss streak** | All-time record | `/players/{id}/matches` |
| **Hero pool diversity** | Number of distinct heroes played in last N games | `/players/{id}/heroes` |

### Tier 3 — Social & Comparison

| Stat | Description | Source endpoint |
|------|-------------|-----------------|
| **Friends played together** | Games + winrate when queued with each other | `/players/{id}/peers` |
| **Head-to-head** | Match IDs where two tracked friends were in same game | Cross-reference match histories |
| **Best teammate** | Friend who most improves your winrate | Peers cross-reference |
| **Relative ranking** | Stack-rank all 5 friends by winrate, KDA, GPM | Aggregate |

### Tier 4 — Advanced (implement last)

| Stat | Description | Source endpoint |
|------|-------------|-----------------|
| **Hero percentile** | "Top X% of players on Juggernaut" | `/players/{id}/rankings` |
| **Improvement trend** | Rolling 7-day winrate over last 90 days | `/players/{id}/matches` (date filter) |
| **Ward score** | Observer wards placed per game | `/recentMatches` (`obs_placed`) |
| **Comeback index** | Avg net-worth deficit reversed in wins | `/matches/{id}` (requires per-match fetch) |

---

## HTML Dashboard Specification

The final deliverable is a **self-contained HTML dashboard** (single file `dashboard.html` or a `/static` folder served by FastAPI).

### Layout

```
┌─────────────────────────────────────────────────────┐
│  🗡 Dota 2 Friend Tracker          [Refresh] [⚙]    │
├─────────────────────────────────────────────────────┤
│  Friend cards (one per player, horizontal scroll)   │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ...  │
│  │ Avatar │ │ Avatar │ │ Avatar │ │ Avatar │       │
│  │ Sherry │ │ Haseeb │ │ Abidi  │ │ Rafay  │       │
│  │ Crusad.│ │ Archon │ │ Legend │ │ Divine │       │
│  │ 54% WR │ │ 48% WR │ │ 61% WR │ │ 52% WR │       │
│  │ 3.2 KDA│ │ 2.1KDA │ │ 4.0KDA │ │ 2.8KDA │       │
│  │ ✓✗✓✓✗ │ │ ✗✗✓✗✓ │ │ ✓✓✓✗✓ │ │ ✓✗✗✓✗ │       │
│  └────────┘ └────────┘ └────────┘ └────────┘       │
├─────────────────────────────────────────────────────┤
│  [Selected friend detail panel — click a card]      │
│  Top heroes | Recent matches table | Peers          │
├─────────────────────────────────────────────────────┤
│  Group stats: who's hottest? who plays together?    │
└─────────────────────────────────────────────────────┘
```

### Tech stack for the HTML dashboard
- Vanilla JS (no framework dependency)
- **Chart.js** (CDN) for bar/line/radar charts
- **Fetch API** to call `http://localhost:8000/dashboard/` on load
- CSS variables for theming (dark Dota-style theme)
- Single file unless assets require separation

### FastAPI integration
Add a `/static` mount in `app/main.py` and serve `dashboard.html` at the root `/`. The dashboard JS calls `/dashboard/` and `/players/{id}/heroes` etc. from the same origin.

---

## Notebook Requirements

Maintain `notebook.ipynb` with the following sections. Keep it runnable top-to-bottom with a live internet connection.

### Sections

1. **Setup & Config** — load `friends.json`, set base URL, import libraries (`httpx`, `pandas`, `matplotlib`, `seaborn`)
2. **Data Fetching** — async functions that mirror `app/client.py` for notebook use; cache responses to avoid re-fetching
3. **Winrate Overview** — bar chart of all friends' overall winrates
4. **KDA Trend** — line chart of KDA across last 20 matches per player
5. **Hero Heatmap** — heatmap of top 10 heroes × friends (colour = winrate)
6. **GPM / XPM Scatter** — scatter plot: GPM vs XPM coloured by win/loss
7. **Recent Form** — sparkline-style win/loss sequence per player
8. **Group Synergy** — matrix of how often friends play together and their shared winrate
9. **Pipeline Diagram** — Mermaid or matplotlib diagram showing: OpenDota API → client.py → routes → dashboard.html

---

## Progress Tracker Requirements

Maintain `PROGRESS.md` in the repo root. Update it every time you complete a task. Format:

```markdown
# Progress Tracker

## Done
- [x] Initial repo scaffold (FastAPI, routes, client, models)
- [x] friends.json populated with 5 players + ID conversion

## In Progress
- [ ] ...

## Backlog
- [ ] HTML dashboard — card layout
- [ ] HTML dashboard — detail panel
- [ ] HTML dashboard — Chart.js charts
- [ ] Notebook — all 9 sections
- [ ] Tier 1 stats fully wired
- [ ] Tier 2 stats
- [ ] Tier 3 stats
- [ ] Tier 4 stats

## Known Issues / Notes
- (add any bugs or blockers here)
```

---

## Coding Conventions

- **Python 3.11+** — use `int | None` union syntax, not `Optional[int]`
- **Async everywhere** — all OpenDota calls must be `async`/`await` via `httpx.AsyncClient`
- **Pydantic v2** — models use `model_dump()` not `.dict()`
- **No hardcoded IDs** — always read from `friends.json` via `app/config.py`
- **Error handling** — wrap OpenDota calls in try/except; return partial data rather than 500
- **One file per router** — don't add routes to `main.py` directly

---

## Running the Project

```bash
# Install
pip install -r requirements.txt

# Start API (default: http://127.0.0.1:8000)
python cli.py serve --reload

# Interactive docs
open http://127.0.0.1:8000/docs

# Dashboard (once built)
open http://127.0.0.1:8000/

# Run notebook
jupyter notebook notebook.ipynb
```

---

## What to Build Next (ordered)

1. `PROGRESS.md` — create and initialise it
2. `notebook.ipynb` — create with all 9 sections (stubs are fine, make them runnable)
3. Tier 1 stats — verify they work end-to-end via `/dashboard/`
4. `dashboard.html` — static file served by FastAPI; card layout first
5. Wire Chart.js charts into the dashboard
6. Tier 2 stats — add to both backend routes and dashboard
7. Tier 3 social stats
8. Tier 4 advanced stats
