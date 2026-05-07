# Dota 2 Performance Tracker

A Python REST API built with **FastAPI** that tracks your friends' Dota 2 games using the free [OpenDota API](https://docs.opendota.com/).

---

## Features

- **Friend list management** – add/remove friends by Steam account ID (stored in `friends.json`)
- **Dashboard endpoint** – one call returns a full snapshot of all friends in parallel
- **Per-player endpoints** – profile, win/loss, recent matches, hero stats, peers, career totals, hero rankings
- **Match detail** – full data for any match ID (items, wards, objectives, all 10 players)
- **No auth required** – works out of the box; optional API key for higher rate limits
- **Interactive docs** – Swagger UI at `/docs`, ReDoc at `/redoc`

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. (Optional) Configure environment

```bash
cp .env.example .env
# Add your OpenDota API key if you have one
```

### 3. Add your friends

Find your friends' **32-bit Steam account IDs** at [steamid.io](https://steamid.io) or from their OpenDota profile URL (`opendota.com/players/<account_id>`).

```bash
# Via CLI
python cli.py add 123456789 --label "FriendName"
python cli.py list

# Or via the API once the server is running
POST /friends/  {"account_id": 123456789, "label": "FriendName"}
```

### 4. Start the server

```bash
python cli.py serve
# or directly:
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000/docs** to explore the API interactively.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | API info and endpoint map |
| `GET` | `/dashboard/` | Full snapshot of all tracked friends |
| `GET` | `/friends/` | List tracked friends |
| `POST` | `/friends/` | Add a friend `{"account_id": int, "label": str}` |
| `DELETE` | `/friends/{account_id}` | Remove a friend |
| `GET` | `/players/{id}` | Player profile (rank, MMR, avatar) |
| `GET` | `/players/{id}/wl` | Win / loss + winrate |
| `GET` | `/players/{id}/recent?limit=20` | Recent matches (with KDA & won enriched) |
| `GET` | `/players/{id}/heroes?limit=10` | Top heroes by games played |
| `GET` | `/players/{id}/peers` | Most frequent teammates |
| `GET` | `/players/{id}/totals` | Career totals (kills, gold, etc.) |
| `GET` | `/players/{id}/rankings` | Hero percentile rankings |
| `GET` | `/matches/{match_id}` | Full match details |

---

## CLI Reference

```bash
python cli.py serve [--host 0.0.0.0] [--port 8000] [--reload]
python cli.py add <account_id> [--label "Nickname"]
python cli.py remove <account_id>
python cli.py list
```

---

## Project Structure

```
Dota 2 tracker/
├── app/
│   ├── main.py        # FastAPI app & lifespan
│   ├── config.py      # Settings (env vars)
│   ├── client.py      # Async OpenDota API client
│   ├── models.py      # Pydantic request/response models
│   └── routes/
│       ├── players.py   # /players endpoints
│       ├── matches.py   # /matches endpoints
│       ├── friends.py   # /friends endpoints
│       └── dashboard.py # /dashboard endpoint
├── cli.py             # Typer CLI (serve, add, remove, list)
├── friends.json       # Tracked friends (auto-managed)
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Rate Limits

The OpenDota API is free with no key for ~50,000 calls/month. For higher limits, get a free API key at [opendota.com/api-keys](https://www.opendota.com/api-keys) and add it to `.env`.
