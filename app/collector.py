"""
Data collector — fetches enriched player and hero stats for the win probability model.

Saves to data/:
  player_role_stats.json   — per player × role: games, wins, winrate, hero breakdown
  hero_matchups.json       — matchup win rates for each hero our friends play
  hero_global_stats.json   — global per-position pick/win rates (from /heroStats)

Run via:  python cli.py refresh-data [--force]
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.client import get_client
from app.config import settings

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

ROLE_NAMES = {1: "Carry", 2: "Mid", 3: "Offlane", 4: "Jungle", 5: "Support"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save(filename: str, payload: dict) -> None:
    with open(DATA_DIR / filename, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def _load(filename: str) -> dict | None:
    path = DATA_DIR / filename
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _is_stale(filename: str, max_age_hours: float = 6.0) -> bool:
    """Return True if the cache file is older than max_age_hours."""
    path = DATA_DIR / filename
    if not path.exists():
        return True
    cached = _load(filename)
    if not cached or "last_updated" not in cached:
        return True
    ts = datetime.fromisoformat(cached["last_updated"])
    age = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    return age > max_age_hours


# ── Role stats ────────────────────────────────────────────────────────────────

async def _fetch_role_stats_for_player(
    client, account_id: int, label: str, limit: int = 100
) -> dict:
    """Fetch role-filtered matches for one player and return structured role stats."""
    roles: dict[str, dict] = {}
    for role_id in range(1, 6):
        try:
            matches = await client.get_matches_by_role(account_id, role_id, limit=limit)
            wins = sum(
                1 for m in matches
                if (m.get("player_slot", 0) < 128) == m.get("radiant_win", False)
            )
            # Per-hero breakdown within this role
            hero_map: dict[int, dict] = {}
            for m in matches:
                hid = m["hero_id"]
                won = (m.get("player_slot", 0) < 128) == m.get("radiant_win", False)
                if hid not in hero_map:
                    hero_map[hid] = {"games": 0, "wins": 0}
                hero_map[hid]["games"] += 1
                if won:
                    hero_map[hid]["wins"] += 1

            roles[str(role_id)] = {
                "role_id": role_id,
                "name": ROLE_NAMES[role_id],
                "games": len(matches),
                "wins": wins,
                "winrate": round(wins / len(matches) * 100, 1) if matches else 0.0,
                "heroes": sorted(
                    [
                        {
                            "hero_id": hid,
                            "games": v["games"],
                            "wins": v["wins"],
                            "winrate": round(v["wins"] / v["games"] * 100, 1),
                        }
                        for hid, v in hero_map.items()
                    ],
                    key=lambda x: -x["games"],
                ),
            }
            await asyncio.sleep(0.35)
        except Exception as exc:
            roles[str(role_id)] = {
                "role_id": role_id,
                "name": ROLE_NAMES[role_id],
                "games": 0,
                "wins": 0,
                "winrate": 0.0,
                "heroes": [],
                "error": str(exc),
            }

    return {"label": label, "account_id": account_id, "roles": roles}


# ── Hero matchups ─────────────────────────────────────────────────────────────

async def _fetch_hero_matchups(client, hero_ids: list[int]) -> dict:
    """Fetch per-hero matchup data for a list of hero IDs."""
    matchups: dict[str, list] = {}
    for hid in hero_ids:
        try:
            data = await client.get_hero_matchups(hid)
            matchups[str(hid)] = data
            await asyncio.sleep(0.3)
        except Exception as exc:
            matchups[str(hid)] = [{"error": str(exc)}]
    return matchups


# ── Main entry ────────────────────────────────────────────────────────────────

async def collect_all(force: bool = False) -> None:
    """
    Fetch and persist all enriched data needed for the probability model.

    Skips a dataset if its cache file is fresh (< 6 h old) and force=False.
    """
    if not settings.friends_file.exists():
        print("[collector] friends.json not found — aborting.")
        return

    with open(settings.friends_file) as fh:
        friends: list[dict] = json.load(fh)["friends"]

    client = get_client()
    now = datetime.now(timezone.utc).isoformat()

    # ── 1. Role stats ──────────────────────────────────────────────────────────
    if force or _is_stale("player_role_stats.json"):
        print("[collector] Fetching role stats per player (5 calls × player)…")
        player_results: dict[str, dict] = {}
        for f in friends:
            aid, label = f["account_id"], f.get("label", str(f["account_id"]))
            print(f"  [{label}] roles…", end=" ", flush=True)
            player_results[str(aid)] = await _fetch_role_stats_for_player(
                client, aid, label
            )
            print("done")
        _save("player_role_stats.json", {"last_updated": now, "players": player_results})
        print(f"  → saved player_role_stats.json")
    else:
        print("[collector] player_role_stats.json is fresh — skipping.")

    # ── 2. Hero matchups ───────────────────────────────────────────────────────
    if force or _is_stale("hero_matchups.json"):
        print("[collector] Resolving top heroes for matchup fetch…")
        hero_ids: set[int] = set()
        for f in friends:
            try:
                heroes = await client.get_heroes(f["account_id"])
                top10 = sorted(heroes, key=lambda h: h.get("games", 0), reverse=True)[:10]
                hero_ids.update(h["hero_id"] for h in top10)
                await asyncio.sleep(0.3)
            except Exception:
                pass
        print(f"  {len(hero_ids)} unique heroes → fetching matchups…")
        matchups = await _fetch_hero_matchups(client, sorted(hero_ids))
        _save("hero_matchups.json", {"last_updated": now, "matchups": matchups})
        print(f"  → saved hero_matchups.json ({len(matchups)} heroes)")
    else:
        print("[collector] hero_matchups.json is fresh — skipping.")

    # ── 3. Global hero stats ───────────────────────────────────────────────────
    if force or _is_stale("hero_global_stats.json"):
        print("[collector] Fetching global hero stats (/heroStats)…")
        try:
            global_stats = await client.get_hero_stats_global()
            _save(
                "hero_global_stats.json",
                {"last_updated": now, "heroes": global_stats},
            )
            print(f"  → saved hero_global_stats.json ({len(global_stats)} heroes)")
        except Exception as exc:
            print(f"  [!] Failed: {exc}")
    else:
        print("[collector] hero_global_stats.json is fresh — skipping.")

    print("\n[collector] Done. Data saved to", DATA_DIR)
