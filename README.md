# Dota 2 Performance Tracker

A Dota 2 dashboard for tracking your group of friends — win rates, hero stats, synergy, and a **live draft win-probability predictor** powered by a calibrated logistic regression model.

Data comes from the free [OpenDota API](https://docs.opendota.com/) and [Stratz API](https://stratz.com/api).

---

## Download & Run (no Python required)

> **This is the recommended path if you just want to use the tracker.**

1. Go to [**Releases**](../../releases) and download the latest `dota-tracker-windows.zip`
2. Extract the zip anywhere (e.g. `C:\dota-tracker\`)
3. Double-click **`dota-tracker.exe`**

A console window walks you through first-time setup:

- **Step 1** — paste your group's Steam IDs (32-bit or 64-bit, both accepted) and nicknames
- **Step 2** — paste a free [Stratz API key](https://stratz.com/api) (optional but recommended for bracket-specific hero meta)
- **Step 3** — the exe pulls 200 matches per player from OpenDota and builds your group's data files (~5–15 min on first run)

When it's done, the browser opens automatically at `http://localhost:8000` with your dashboard.

The exe is **fully self-contained** — every per-group data file is generated locally on first run. Nothing from the developer's machine is bundled. Subsequent launches start in seconds.

---

## Quick Start (from source)

Use this if you want to modify the code or run the notebook.

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Add your friends

```bash
python cli.py add 123456789 --label "YourName"
python cli.py list
```

### 3. Fetch match data & model signals

```bash
# Full match history (200 matches per player, ~5–10 min first run)
python cli.py refresh-matches

# Hero stats, matchup matrix, global meta from OpenDota + Stratz
python cli.py refresh-data
```

### 4. (Optional) Calibrate the win probability model weights

Run notebook **§14** in `notebook.ipynb` to fit signal weights from your group's match history and save `data/model_weights.json`.

### 5. Start the server

```bash
python cli.py serve
```

Open **http://127.0.0.1:8000** for the dashboard, or **http://127.0.0.1:8000/docs** for the interactive API.

---

## Features

- **Friend cards** — win rate, KDA, GPM/XPM, recent form, streak, rank badge
- **Player detail panel** — top heroes, recent matches, role breakdown, consistency metrics
- **Group charts** — win rate, KDA, GPM/XPM, hero damage comparison
- **Role performance heatmap** — each player × each role, colour-coded by win rate
- **Group synergy matrix** — win rate when queueing together
- **Draft predictor** — pick 10 heroes + roles → radiant win probability with signal breakdown
  - Tier A: per-player hero fit, role fit, hero×role conditional, recent form
  - Tier B: teammate synergy pairs
  - Tier C: hero matchup matrix (25 pairings, role-weighted)
  - Tier D: bracket-specific global meta (Stratz Legend/Ancient data)
  - Weights calibrated via logistic regression on your group's match history

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serves the dashboard HTML |
| `GET` | `/dashboard/` | Full snapshot of all tracked friends |
| `GET` | `/friends/` | List tracked friends |
| `POST` | `/friends/` | Add a friend `{"account_id": int, "label": str}` |
| `DELETE` | `/friends/{account_id}` | Remove a friend |
| `GET` | `/players/{id}` | Player profile (rank, MMR, avatar) |
| `GET` | `/players/{id}/wl` | Win / loss + winrate |
| `GET` | `/players/{id}/recent` | Recent matches |
| `GET` | `/players/{id}/heroes` | Top heroes by games played |
| `GET` | `/players/{id}/peers` | Most frequent teammates |
| `GET` | `/heroes/reference` | Full hero name/ID list |
| `GET` | `/analytics/dashboard` | Group analytics (role heatmap, synergy) |
| `POST` | `/probability/predict` | Win probability for a 10-player draft |
| `POST` | `/probability/reload` | Reload model from disk after refresh-data |
| `GET` | `/docs` | Swagger UI |

---

## CLI Reference

```bash
python cli.py serve [--host 0.0.0.0] [--port 8000] [--reload]
python cli.py add <account_id> [--label "Nickname"]
python cli.py remove <account_id>
python cli.py list
python cli.py refresh-matches [--limit 200] [--force]
python cli.py refresh-data [--force]
```

---

## Diagnostic / smoke test

If the dashboard isn't loading data correctly, run the smoke test to see exactly which API calls are failing and why:

```bash
python smoke_test.py
```

It hits every OpenDota endpoint, the probability model, and the FastAPI routes — printing PASS/FAIL with timings and error reasons.

---

## Building the exe yourself

```bash
pip install pyinstaller
pyinstaller dota_tracker.spec
```

Output is in `dist/dota-tracker/`. Zip that folder and upload to GitHub Releases.

---

## Project Structure

```
Dota 2 tracker/
├── app/
│   ├── main.py              # FastAPI app & lifespan
│   ├── config.py            # Settings (env vars, ROOT_DIR)
│   ├── client.py            # Async OpenDota API client
│   ├── models.py            # Pydantic request/response models
│   ├── probability.py       # Win probability model (all tiers)
│   ├── collector.py         # Data refresh (OpenDota + Stratz)
│   ├── match_cache.py       # DEEP match cache helpers
│   ├── stratz.py            # Stratz GraphQL client
│   └── routes/
│       ├── players.py
│       ├── matches.py
│       ├── friends.py
│       ├── dashboard.py
│       ├── heroes.py
│       ├── analytics.py
│       └── probability.py
├── static/
│   └── dashboard.html       # Single-page dashboard + draft predictor
├── data/                    # Generated — not committed
│   ├── match_cache/         # Full match JSON (200 per player)
│   ├── diff_player_x_*.parquet
│   ├── hero_matchups.json
│   ├── hero_global_stats_merged.json
│   └── model_weights.json   # Calibrated signal weights
├── launcher.py              # Exe entry point (opens browser + starts server)
├── dota_tracker.spec        # PyInstaller build spec
├── cli.py                   # Typer CLI
├── notebook.ipynb           # Exploration + calibration notebook
├── friends.json             # Tracked friends (user-managed)
├── requirements.txt
└── .env                     # API keys (not committed)
```

---

## Environment variables (`.env`)

```env
OPENDOTA_API_KEY=           # optional — raises rate limit from 50k to 2M calls/month
STRATZ_API_KEY=             # optional — enables bracket-specific hero meta (Tier D)
STRATZ_BRACKETS=["LEGEND_ANCIENT"]   # adjust to your group's MMR range
```

Get a free OpenDota key at [opendota.com/api-keys](https://www.opendota.com/api-keys).
Get a free Stratz key at [stratz.com/api](https://stratz.com/api).

---

## Rate Limits

| Source | Free tier |
|--------|-----------|
| OpenDota (no key) | ~50,000 calls/month |
| OpenDota (with key) | ~2,000,000 calls/month |
| Stratz (free key) | ~1 req/sec |
