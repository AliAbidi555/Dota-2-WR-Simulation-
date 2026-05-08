"""
Match history cache for the Dota 2 Tracker.

Two-level cache stored in data/match_cache/:
  player_match_ids/{account_id}.json  — ordered match list (basic stats) per player
  matches/{match_id}.json             — full match JSON per match

Match files are written once and never overwritten (content never changes).
Player match-list files can be refreshed with force=True.

Entry points:
  await collect_match_history(account_ids, limit, force)  — populate cache
  load_player_match_list(account_id) -> list[dict]         — read from cache
  load_match(match_id)               -> dict | None        — read from cache
  extract_player_stats(match, account_id) -> dict | None   — parse one player row
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

import httpx

BASE_URL        = "https://api.opendota.com/api"
HEADERS         = {"User-Agent": "DotaTracker/1.0"}
CALL_DELAY      = 1.05          # seconds between API calls — keeps under 60 req/min free limit
REQUEST_TIMEOUT = 30

MATCH_CACHE_DIR = Path("data/match_cache")
PLAYER_IDS_DIR  = MATCH_CACHE_DIR / "player_match_ids"
MATCHES_DIR     = MATCH_CACHE_DIR / "matches"


def _ensure_dirs() -> None:
    PLAYER_IDS_DIR.mkdir(parents=True, exist_ok=True)
    MATCHES_DIR.mkdir(parents=True, exist_ok=True)


# ── Sync read helpers (safe to call from notebook / sync contexts) ────────────

def load_player_match_list(account_id: int) -> list[dict]:
    """Return cached match list for a player, or [] if not yet fetched."""
    f = PLAYER_IDS_DIR / f"{account_id}.json"
    return json.loads(f.read_text(encoding='utf-8')) if f.exists() else []


def _read_match_file(f: Path) -> Optional[str]:
    """Read a match file, migrating legacy cp1252 files to UTF-8 in place."""
    try:
        content = f.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        content = f.read_text(encoding='latin-1')
        f.write_text(content, encoding='utf-8')
    return content if content.strip() else None


def load_match(match_id: int) -> Optional[dict]:
    """Return cached full match dict, or None if not yet fetched or file is empty."""
    f = MATCHES_DIR / f"{match_id}.json"
    if not f.exists():
        return None
    content = _read_match_file(f)
    return json.loads(content) if content else None


def match_cached(match_id: int) -> bool:
    return (MATCHES_DIR / f"{match_id}.json").exists()


def player_list_cached(account_id: int) -> bool:
    return (PLAYER_IDS_DIR / f"{account_id}.json").exists()


def cache_stats() -> dict:
    """Return counts of cached files."""
    _ensure_dirs()
    return {
        "players": len(list(PLAYER_IDS_DIR.iterdir())),
        "matches": len(list(MATCHES_DIR.iterdir())),
    }


# ── Core extraction helper ────────────────────────────────────────────────────

def extract_player_stats(match: dict, account_id: int) -> Optional[dict]:
    """
    Find `account_id` in a full match dict and return a flat stats row.
    Returns None if the player isn't found (private profile / abandoned match).
    """
    for p in match.get("players", []):
        if p.get("account_id") != account_id:
            continue
        is_rad = p.get("player_slot", 0) < 128
        won    = match.get("radiant_win", False) if is_rad else not match.get("radiant_win", False)
        dur    = max(match.get("duration", 1), 1)
        kills, deaths, assists = p.get("kills", 0), p.get("deaths", 0), p.get("assists", 0)
        return {
            "match_id":        match["match_id"],
            "hero_id":         p.get("hero_id"),
            "kills":           kills,
            "deaths":          deaths,
            "assists":         assists,
            "gold_per_min":    p.get("gold_per_min", 0),
            "xp_per_min":      p.get("xp_per_min", 0),
            "last_hits":       p.get("last_hits", 0),
            "denies":          p.get("denies", 0),
            "hero_damage":     p.get("hero_damage", 0),
            "tower_damage":    p.get("tower_damage", 0),
            "hero_healing":    p.get("hero_healing", 0),
            "obs_placed":      p.get("obs_placed", 0),
            "sen_placed":      p.get("sen_placed", 0),
            "buyback_count":   p.get("buyback_count", 0),
            "net_worth":       p.get("net_worth", 0),
            "actions_per_min": p.get("actions_per_min", 0),
            "lane_role":       p.get("lane_role"),
            "is_roaming":      p.get("is_roaming", False),
            "duration":        dur,
            "won":             won,
            "kda":             round((kills + assists) / max(deaths, 1), 2),
            "dmg_per_min":     round(p.get("hero_damage", 0) / dur * 60, 1),
            "lh_per_min":      round(p.get("last_hits", 0)  / dur * 60, 2),
        }
    return None


# ── Async collection ──────────────────────────────────────────────────────────

async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict | list:
    resp = await client.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    await asyncio.sleep(CALL_DELAY)
    return resp.json()


async def collect_match_history(
    account_ids: list[int],
    limit: int = 200,
    force: bool = False,
) -> None:
    """
    Populate data/match_cache/ for all given account IDs.

    Phase 1 — match ID lists: one API call per player (skipped if cached and not force).
    Phase 2 — full matches:   one call per unique uncached match_id.
                              Already-cached matches are never re-fetched.
    """
    _ensure_dirs()

    # ── Phase 1: fetch per-player match lists ─────────────────────────────────
    print("Phase 1 — match ID lists")
    all_match_ids: set[int] = set()

    async with httpx.AsyncClient() as client:
        for aid in account_ids:
            cache_file = PLAYER_IDS_DIR / f"{aid}.json"
            if cache_file.exists() and not force:
                data = json.loads(cache_file.read_text(encoding='utf-8'))
                print(f"  {aid}  {len(data)} matches (cached)")
            else:
                print(f"  {aid}  fetching {limit} matches ...", end=" ", flush=True)
                try:
                    data = await _fetch_json(
                        client,
                        f"{BASE_URL}/players/{aid}/matches?limit={limit}&significant=1",
                    )
                    cache_file.write_text(json.dumps(data), encoding='utf-8')
                    print(f"{len(data)} matches")
                except Exception as exc:
                    print(f"ERROR: {exc}")
                    data = []
            all_match_ids.update(m["match_id"] for m in data)

    # ── Phase 2: fetch uncached full matches ──────────────────────────────────
    to_fetch = sorted(mid for mid in all_match_ids if not match_cached(mid))
    already  = len(all_match_ids) - len(to_fetch)
    print(
        f"\nPhase 2 — full matches\n"
        f"  {len(all_match_ids)} unique across all players\n"
        f"  {already} already cached, {len(to_fetch)} to fetch "
        f"(~{len(to_fetch) * CALL_DELAY / 60:.0f} min)"
    )

    if not to_fetch:
        print("  Nothing to fetch.")
        return

    errors = 0
    async with httpx.AsyncClient() as client:
        for i, mid in enumerate(to_fetch):
            if i > 0 and i % 100 == 0:
                print(f"  [{i}/{len(to_fetch)}]  errors={errors}", flush=True)
            try:
                resp = await client.get(
                    f"{BASE_URL}/matches/{mid}", headers=HEADERS, timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
                if not resp.text.strip():
                    errors += 1
                    continue
                (MATCHES_DIR / f"{mid}.json").write_text(resp.text, encoding='utf-8')
            except Exception as exc:
                errors += 1
                if errors <= 5:
                    print(f"  [warn] {mid}: {exc}")
            await asyncio.sleep(CALL_DELAY)

    total = len(list(MATCHES_DIR.iterdir()))
    print(f"\nDone — {len(to_fetch) - errors} fetched, {errors} errors. "
          f"Cache total: {total} matches.")
