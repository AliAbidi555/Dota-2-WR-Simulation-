"""
/analytics — serve cached player and hero analytics data.

These endpoints read from data/ files written by app/collector.py.
Run  `python cli.py refresh-data`  to populate the cache.
"""

import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.collector import collect_all

router = APIRouter(prefix="/analytics", tags=["analytics"])

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _read_cache(filename: str):
    path = DATA_DIR / filename
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No cached data found. Run: python cli.py refresh-data",
        )
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@router.get("/player-role-stats")
async def get_player_role_stats():
    """
    Per-player, per-role stats: games, wins, winrate, and hero breakdown.
    Each role entry lists which heroes the player used in that role and their WR.
    """
    return _read_cache("player_role_stats.json")


@router.get("/hero-matchups")
async def get_hero_matchups():
    """
    Hero matchup data for every hero our friends play (top 10 per player).
    For each hero: win rate against every other hero.
    """
    return _read_cache("hero_matchups.json")


@router.get("/hero-matchups/{hero_id}")
async def get_hero_matchups_by_id(hero_id: int):
    """Matchup data for a single hero."""
    cache = _read_cache("hero_matchups.json")
    matchup = cache.get("matchups", {}).get(str(hero_id))
    if matchup is None:
        raise HTTPException(status_code=404, detail=f"No matchup data for hero {hero_id}")
    return {"hero_id": hero_id, "last_updated": cache.get("last_updated"), "matchups": matchup}


@router.get("/hero-global-stats")
async def get_hero_global_stats():
    """
    Global hero stats from OpenDota /heroStats.
    Includes per-position (1–5) pick count and win count for every hero —
    use {pos}_win / {pos}_pick to derive expected WR for a hero in a given role.
    """
    return _read_cache("hero_global_stats.json")


@router.post("/refresh")
async def refresh_data(background_tasks: BackgroundTasks, force: bool = False):
    """
    Trigger a full data re-collection in the background.
    Pass ?force=true to bypass the 6-hour freshness check.
    """
    background_tasks.add_task(collect_all, force)
    return {"message": "Data collection started in background. Check server logs for progress."}
