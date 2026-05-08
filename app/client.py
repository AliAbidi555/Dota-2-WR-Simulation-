"""
Async client for the OpenDota REST API.
https://docs.opendota.com/

Resilience features:
  - Aggregate endpoints (/wl, /heroes, /peers, /totals, /rankings) get a
    longer 60s timeout because OpenDota recomputes them server-side from
    the player's full match history.
  - One automatic retry on read timeout / connection errors before giving up.
  - In-memory TTL cache (5 min) for read-heavy endpoints so dashboard reloads
    don't keep hitting OpenDota.
"""

import asyncio
import time
from typing import Any

import httpx

from app.config import settings


# Per-endpoint timeout overrides (seconds).  Aggregate endpoints recompute
# from the player's full match history server-side and can take 30-45 s.
DEFAULT_TIMEOUT  = 30.0
SLOW_TIMEOUT     = 60.0
SLOW_PATHS = ("/wl", "/heroes", "/peers", "/totals", "/rankings")

# Simple TTL cache — endpoint path -> (expiry_unix, value).
# Reset on process restart, which is fine for our use case.
_TTL_CACHE: dict[str, tuple[float, Any]] = {}
CACHE_TTL_SECONDS = 300  # 5 minutes


def _is_slow(path: str) -> bool:
    return any(path.endswith(s) for s in SLOW_PATHS)


def _cache_key(path: str, params: dict) -> str:
    if not params:
        return path
    parts = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"{path}?{parts}"


class OpenDotaClient:
    """Thin async wrapper around the OpenDota API."""

    def __init__(self) -> None:
        params: dict[str, str] = {}
        if settings.opendota_api_key:
            params["api_key"] = settings.opendota_api_key

        self._client = httpx.AsyncClient(
            base_url=settings.opendota_base_url,
            params=params,
            timeout=DEFAULT_TIMEOUT,
        )

    async def _get(self, path: str, **params: Any) -> Any:
        """
        GET with caching, retry-on-timeout, and per-endpoint timeout overrides.

        - Hot endpoints (5 min TTL cache): /wl, /heroes, /peers, /totals, /rankings
        - One retry with the slow timeout on httpx.ReadTimeout / ConnectError.
        """
        key = _cache_key(path, params)
        now = time.time()

        # Cache hit?
        cached = _TTL_CACHE.get(key)
        if cached and cached[0] > now:
            return cached[1]

        timeout = SLOW_TIMEOUT if _is_slow(path) else DEFAULT_TIMEOUT

        try:
            return await self._fetch(path, params, timeout, key)
        except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError):
            # One retry with the slow timeout — OpenDota occasionally takes a
            # second pass to warm the cache for heavy aggregate queries.
            await asyncio.sleep(0.5)
            return await self._fetch(path, params, SLOW_TIMEOUT, key)

    async def _fetch(self, path: str, params: dict, timeout: float, cache_key: str) -> Any:
        response = await self._client.get(path, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if _is_slow(path):
            _TTL_CACHE[cache_key] = (time.time() + CACHE_TTL_SECONDS, data)
        return data

    # ------------------------------------------------------------------ #
    # Players
    # ------------------------------------------------------------------ #

    async def get_player(self, account_id: int) -> dict:
        """Fetch a player's profile (rank, MMR estimate, name, avatar…)."""
        return await self._get(f"/players/{account_id}")

    async def get_win_loss(self, account_id: int) -> dict:
        """Return win / loss counts for a player."""
        return await self._get(f"/players/{account_id}/wl")

    async def get_recent_matches(self, account_id: int, limit: int | None = None) -> list[dict]:
        """Return recent matches for a player (default limit from settings)."""
        limit = limit or settings.default_match_limit
        return await self._get(f"/players/{account_id}/recentMatches")

    async def get_matches(
        self,
        account_id: int,
        limit: int | None = None,
        hero_id: int | None = None,
        significant: int = 1,
    ) -> list[dict]:
        """Return filtered matches for a player."""
        params: dict[str, Any] = {"limit": limit or settings.default_match_limit}
        if hero_id is not None:
            params["hero_id"] = hero_id
        params["significant"] = significant
        return await self._get(f"/players/{account_id}/matches", **params)

    async def get_heroes(self, account_id: int) -> list[dict]:
        """Return per-hero stats for a player (games, wins, KDA…)."""
        return await self._get(f"/players/{account_id}/heroes")

    async def get_peers(self, account_id: int) -> list[dict]:
        """Return players this account has played with most."""
        return await self._get(f"/players/{account_id}/peers")

    async def get_totals(self, account_id: int) -> list[dict]:
        """Return career totals (kills, deaths, gold, etc.)."""
        return await self._get(f"/players/{account_id}/totals")

    async def get_rankings(self, account_id: int) -> list[dict]:
        """Return hero rankings (percentile for each hero played)."""
        return await self._get(f"/players/{account_id}/rankings")

    async def get_matches_by_role(
        self, account_id: int, lane_role: int, limit: int = 100
    ) -> list[dict]:
        """Return matches filtered to a specific lane role (1=Carry … 5=Support)."""
        return await self._get(
            f"/players/{account_id}/matches",
            limit=limit,
            lane_role=lane_role,
            significant=1,
        )

    # ------------------------------------------------------------------ #
    # Matches
    # ------------------------------------------------------------------ #

    async def get_match(self, match_id: int) -> dict:
        """Fetch full details for a single match."""
        return await self._get(f"/matches/{match_id}")

    # ------------------------------------------------------------------ #
    # Heroes reference + matchups
    # ------------------------------------------------------------------ #

    async def get_heroes_reference(self) -> list[dict]:
        """Return hero reference list (id → name, primary_attr, etc.)."""
        return await self._get("/heroes")

    async def get_hero_matchups(self, hero_id: int) -> list[dict]:
        """Return matchup win rates for a hero against every other hero."""
        return await self._get(f"/heroes/{hero_id}/matchups")

    async def get_hero_stats_global(self) -> list[dict]:
        """Return global hero stats including per-position pick/win counts."""
        return await self._get("/heroStats")

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def close(self) -> None:
        await self._client.aclose()


# Module-level singleton – shared across requests
_client: OpenDotaClient | None = None


def get_client() -> OpenDotaClient:
    global _client
    if _client is None:
        _client = OpenDotaClient()
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
