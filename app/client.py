"""
Async client for the OpenDota REST API.
https://docs.opendota.com/
"""

import httpx
from typing import Any
from app.config import settings


class OpenDotaClient:
    """Thin async wrapper around the OpenDota API."""

    def __init__(self) -> None:
        params: dict[str, str] = {}
        if settings.opendota_api_key:
            params["api_key"] = settings.opendota_api_key

        self._client = httpx.AsyncClient(
            base_url=settings.opendota_base_url,
            params=params,
            timeout=15.0,
        )

    async def _get(self, path: str, **params: Any) -> Any:
        """Make a GET request and return parsed JSON."""
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

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
