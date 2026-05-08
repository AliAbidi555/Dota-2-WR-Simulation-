"""
/dashboard – aggregated view of all tracked friends
"""

import asyncio
import json
import statistics
from fastapi import APIRouter, Query
from app.client import get_client
from app.config import settings
from app.models import FriendsConfig, FriendSummary, DashboardResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

ROLE_NAMES = {1: "Carry", 2: "Mid", 3: "Offlane", 4: "Jungle", 5: "Support"}


def _compute_streak(matches: list[dict]) -> int:
    """Positive = win streak, negative = loss streak (most recent first)."""
    if not matches:
        return 0
    first_won = matches[0]["won"]
    streak = 0
    for m in matches:
        if m["won"] == first_won:
            streak += 1 if first_won else -1
        else:
            break
    return streak


async def _build_friend_summary(account_id: int, label: str | None, limit: int) -> FriendSummary:
    client = get_client()

    profile, wl, recent, heroes = await asyncio.gather(
        client.get_player(account_id),
        client.get_win_loss(account_id),
        client.get_recent_matches(account_id, limit=limit),
        client.get_heroes(account_id),
        return_exceptions=True,
    )

    warnings: list[str] = []
    for name, val in (("profile", profile), ("wl", wl), ("recent", recent), ("heroes", heroes)):
        if isinstance(val, BaseException):
            warnings.append(f"{name}: {type(val).__name__}")

    # ── Profile ───────────────────────────────────────────────────────────────
    persona = label or (
        profile.get("profile", {}).get("personaname") if isinstance(profile, dict) else None
    )
    avatar   = profile.get("profile", {}).get("avatarfull") if isinstance(profile, dict) else None
    rank_tier = profile.get("rank_tier") if isinstance(profile, dict) else None

    # ── Win / loss ────────────────────────────────────────────────────────────
    # When the /wl call failed, leave fields as None so the UI shows "—" rather
    # than misleading 0% / 0W-0L.  A successful call with genuinely zero games
    # still returns wins=0, losses=0, winrate=0.0 (distinct from None).
    if isinstance(wl, dict):
        wins   = int(wl.get("win", 0))
        losses = int(wl.get("lose", 0))
        total  = wins + losses
        winrate = round(wins / total * 100, 1) if total else 0.0
    else:
        wins, losses, winrate = None, None, None

    # ── Enrich recent matches ─────────────────────────────────────────────────
    enriched: list[dict] = []
    if isinstance(recent, list):
        for m in recent[:limit]:
            is_rad = m.get("player_slot", 0) < 128
            won    = m["radiant_win"] if is_rad else not m["radiant_win"]
            k, d, a = m.get("kills", 0), m.get("deaths", 0), m.get("assists", 0)
            enriched.append({
                **m,
                "won": won,
                "kda": round((k + a) / max(d, 1), 2),
            })

    n = len(enriched)

    # ── Tier 1 aggregates ─────────────────────────────────────────────────────
    avg_kda = round(sum(m["kda"] for m in enriched) / n, 2)               if n else 0.0
    avg_gpm = round(sum(m.get("gold_per_min", 0) for m in enriched) / n, 1) if n else 0.0
    avg_xpm = round(sum(m.get("xp_per_min",   0) for m in enriched) / n, 1) if n else 0.0
    recent_form    = [m["won"] for m in enriched[:10]]
    current_streak = _compute_streak(enriched)

    # ── Tier 2 aggregates ─────────────────────────────────────────────────────
    avg_hero_damage_per_min = 0.0
    avg_last_hits_per_min   = 0.0
    avg_tower_damage        = 0.0
    kda_std = 0.0
    gpm_std = 0.0

    if n:
        avg_hero_damage_per_min = round(
            sum(m.get("hero_damage", 0) / max(m.get("duration", 1), 1) * 60
                for m in enriched) / n, 1
        )
        avg_last_hits_per_min = round(
            sum(m.get("last_hits", 0) / max(m.get("duration", 1), 1) * 60
                for m in enriched) / n, 2
        )
        avg_tower_damage = round(
            sum(m.get("tower_damage", 0) for m in enriched) / n, 0
        )
        if n > 1:
            kda_std = round(statistics.stdev([m["kda"] for m in enriched]), 2)
            gpm_std = round(statistics.stdev([m.get("gold_per_min", 0) for m in enriched]), 1)

    # Role breakdown from lane_role field (present in recentMatches)
    role_buckets: dict[str, dict] = {}
    for m in enriched:
        role = m.get("lane_role")
        if not role:
            continue
        name = ROLE_NAMES.get(role, f"Role {role}")
        if name not in role_buckets:
            role_buckets[name] = {"games": 0, "wins": 0}
        role_buckets[name]["games"] += 1
        if m["won"]:
            role_buckets[name]["wins"] += 1
    role_stats = {
        k: {**v, "winrate": round(v["wins"] / v["games"] * 100, 1) if v["games"] else 0.0}
        for k, v in role_buckets.items()
    }

    # Duration buckets
    dur_buckets = {
        "<30min":  {"games": 0, "wins": 0},
        "30-45min": {"games": 0, "wins": 0},
        ">45min":  {"games": 0, "wins": 0},
    }
    for m in enriched:
        d = m.get("duration", 0)
        key = "<30min" if d < 1800 else ("30-45min" if d < 2700 else ">45min")
        dur_buckets[key]["games"] += 1
        if m["won"]:
            dur_buckets[key]["wins"] += 1
    duration_stats = {
        k: {**v, "winrate": round(v["wins"] / v["games"] * 100, 1) if v["games"] else 0.0}
        for k, v in dur_buckets.items()
    }

    hero_pool_size = len({m.get("hero_id") for m in enriched if m.get("hero_id")})

    # ── Top heroes ────────────────────────────────────────────────────────────
    top_heroes: list[dict] = []
    if isinstance(heroes, list):
        for h in sorted(heroes, key=lambda h: h.get("games", 0), reverse=True)[:5]:
            g = h.get("games", 0)
            h["winrate"] = round(h.get("win", 0) / g * 100, 1) if g else 0.0
        top_heroes = sorted(heroes, key=lambda h: h.get("games", 0), reverse=True)[:5]

    return FriendSummary(
        account_id=account_id,
        label=label,
        personaname=persona,
        avatarfull=avatar,
        rank_tier=rank_tier,
        wins=wins,
        losses=losses,
        winrate=winrate,
        avg_kda=avg_kda,
        avg_gpm=avg_gpm,
        avg_xpm=avg_xpm,
        recent_form=recent_form,
        current_streak=current_streak,
        avg_hero_damage_per_min=avg_hero_damage_per_min,
        avg_last_hits_per_min=avg_last_hits_per_min,
        avg_tower_damage=avg_tower_damage,
        kda_std=kda_std,
        gpm_std=gpm_std,
        hero_pool_size=hero_pool_size,
        role_stats=role_stats,
        duration_stats=duration_stats,
        recent_matches=enriched,
        top_heroes=top_heroes,
        warnings=warnings,
    )


@router.get("/", response_model=DashboardResponse)
async def get_dashboard(
    limit: int = Query(default=20, ge=1, le=50, description="Recent matches per friend"),
):
    """
    Full performance snapshot for all tracked friends.

    Tier 1: profile, career WR, KDA/GPM/XPM averages, recent form, streak, top heroes.
    Tier 2: damage/min, LH/min, KDA consistency (std dev), role breakdown, duration buckets.
    """
    if not settings.friends_file.exists():
        return DashboardResponse(friends=[])

    with open(settings.friends_file) as fh:
        config = FriendsConfig(**json.load(fh))

    if not config.friends:
        return DashboardResponse(friends=[])

    results = await asyncio.gather(
        *[_build_friend_summary(f.account_id, f.label, limit) for f in config.friends],
        return_exceptions=True,
    )
    return DashboardResponse(friends=[r for r in results if isinstance(r, FriendSummary)])
