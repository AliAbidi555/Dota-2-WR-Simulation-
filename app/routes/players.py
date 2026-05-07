"""
/players endpoints
"""

from fastapi import APIRouter, HTTPException, Query
from app.client import get_client
from app.models import WinLoss

router = APIRouter(prefix="/players", tags=["players"])


@router.get("/{account_id}")
async def get_player(account_id: int):
    """
    Full player profile: Steam name, avatar, rank tier, MMR estimate.
    """
    try:
        return await get_client().get_player(account_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{account_id}/wl", response_model=WinLoss)
async def get_win_loss(account_id: int):
    """
    Win / loss record with computed winrate.
    """
    try:
        data = await get_client().get_win_loss(account_id)
        total = data["win"] + data["lose"]
        return WinLoss(
            win=data["win"],
            lose=data["lose"],
            winrate=round(data["win"] / total * 100, 1) if total else 0.0,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{account_id}/recent")
async def get_recent_matches(
    account_id: int,
    limit: int = Query(default=20, ge=1, le=100, description="Number of recent matches"),
):
    """
    Recent matches with KDA, hero, win/loss, GPM, XPM.
    Each match includes a computed `won` and `kda` field.
    """
    try:
        matches = await get_client().get_recent_matches(account_id, limit=limit)
        enriched = []
        for m in matches[:limit]:
            is_radiant = m.get("player_slot", 0) < 128
            won = m["radiant_win"] if is_radiant else not m["radiant_win"]
            kills = m.get("kills", 0)
            deaths = m.get("deaths", 0)
            assists = m.get("assists", 0)
            kda = round((kills + assists) / max(deaths, 1), 2)
            enriched.append({**m, "won": won, "kda": kda})
        return enriched
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{account_id}/heroes")
async def get_hero_stats(
    account_id: int,
    limit: int = Query(default=10, ge=1, le=120, description="Top N heroes by games played"),
):
    """
    Per-hero stats sorted by games played.
    Includes computed winrate per hero.
    """
    try:
        heroes = await get_client().get_heroes(account_id)
        heroes.sort(key=lambda h: h.get("games", 0), reverse=True)
        for h in heroes:
            games = h.get("games", 0)
            wins = h.get("win", 0)
            h["winrate"] = round(wins / games * 100, 1) if games else 0.0
        return heroes[:limit]
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{account_id}/peers")
async def get_peers(
    account_id: int,
    limit: int = Query(default=10, ge=1, le=50),
):
    """
    Players this account has played with most. Includes winrate together.
    """
    try:
        peers = await get_client().get_peers(account_id)
        peers.sort(key=lambda p: p.get("games", 0), reverse=True)
        for p in peers:
            games = p.get("games", 0)
            wins = p.get("win", 0)
            p["winrate_together"] = round(wins / games * 100, 1) if games else 0.0
        return peers[:limit]
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{account_id}/totals")
async def get_totals(account_id: int):
    """
    Career totals: kills, deaths, assists, gold, XP, last hits, etc.
    """
    try:
        return await get_client().get_totals(account_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{account_id}/rankings")
async def get_rankings(account_id: int):
    """
    Hero rankings: percentile vs. all OpenDota players on each hero.
    """
    try:
        return await get_client().get_rankings(account_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
