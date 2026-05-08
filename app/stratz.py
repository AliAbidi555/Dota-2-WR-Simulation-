"""
Stratz API client for bracket-specific, patch-aware hero meta data.
Get a free API key at: https://stratz.com/api

Uses curl_cffi to bypass Cloudflare (regular httpx gets 403).

Data saved to:
  data/hero_global_stats_stratz.json  -- hero win rates by position + bracket
  data/hero_global_stats_merged.json  -- Stratz + OpenDota merged (preferred by model)
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from curl_cffi import requests as cffi_requests

STRATZ_GRAPHQL = "https://api.stratz.com/graphql"
# curl_cffi impersonation profile - Chrome 110 passes Cloudflare
IMPERSONATE    = "chrome110"
CALL_DELAY     = 1.2   # free tier: ~1 req/sec sustained

# Stratz RankBracketBasicEnum values (coarser than OpenDota's 1-8 scale)
BRACKET_GROUPS: dict[str, int] = {
    "UNCALIBRATED":   0,
    "HERALD_GUARDIAN": 1,
    "CRUSADER_ARCHON": 2,
    "LEGEND_ANCIENT":  3,
    "DIVINE_IMMORTAL": 4,
    "ALL":             5,
}
# integer -> Stratz enum name
BRACKET_GROUP_ENUM: dict[int, str] = {v: k for k, v in BRACKET_GROUPS.items()}

# Stratz position index (1-5) -> GraphQL enum name
POSITION_ENUM: dict[int, str] = {
    1: "POSITION_1", 2: "POSITION_2", 3: "POSITION_3",
    4: "POSITION_4", 5: "POSITION_5",
}

# Minimum pick count to trust a Stratz win-rate estimate
MIN_PICKS = 100

_HERO_STATS_QUERY = """
query HeroPosMeta($bracketBasicIds: [RankBracketBasicEnum], $positionIds: [MatchPlayerPositionType]) {
  heroStats {
    stats(bracketBasicIds: $bracketBasicIds, positionIds: $positionIds) {
      heroId
      winCount
      matchCount
    }
  }
}
"""


class StratzClient:
    """
    Async Stratz GraphQL client using curl_cffi to bypass Cloudflare.
    Requires a free Bearer token from stratz.com/api.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _gql_sync(self, query: str, variables: Optional[dict] = None) -> dict:
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables
        resp = cffi_requests.post(
            STRATZ_GRAPHQL,
            impersonate=IMPERSONATE,
            headers=self._headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        if "errors" in body:
            raise RuntimeError(f"Stratz GraphQL errors: {body['errors']}")
        return body.get("data", {})

    async def _gql(self, query: str, variables: Optional[dict] = None) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._gql_sync, query, variables)

    async def get_hero_position_stats(
        self,
        bracket_names: list[str],
    ) -> dict[int, dict[int, dict]]:
        """
        Fetch hero win rates at each position for the given rank bracket groups.

        Makes 5 GraphQL calls (one per position) and returns:
            {hero_id: {role_id_1-5: {"win": int, "pick": int}}}

        Heroes / positions with fewer than MIN_PICKS games are omitted.

        bracket_names must be valid RankBracketBasicEnum values, e.g.:
            ["LEGEND_ANCIENT"] or ["LEGEND_ANCIENT", "DIVINE_IMMORTAL"]
        """
        result: dict[int, dict[int, dict]] = {}

        for pos_idx, pos_enum in POSITION_ENUM.items():
            variables = {
                "bracketBasicIds": bracket_names,
                "positionIds":     [pos_enum],
            }
            try:
                data  = await self._gql(_HERO_STATS_QUERY, variables)
                stats = (data.get("heroStats") or {}).get("stats") or []
                for h in stats:
                    hid  = int(h["heroId"])
                    pick = int(h.get("matchCount", 0))
                    win  = int(h.get("winCount",   0))
                    if pick < MIN_PICKS:
                        continue
                    result.setdefault(hid, {})[pos_idx] = {"win": win, "pick": pick}
                print(f"  [stratz] {pos_enum}: {len(stats)} heroes")
            except Exception as exc:
                print(f"  [stratz] {pos_enum} fetch failed: {exc}")
            await asyncio.sleep(CALL_DELAY)

        return result

    async def close(self) -> None:
        pass  # curl_cffi uses stateless requests; nothing to close


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def to_opendota_format(
    raw: dict[int, dict[int, dict]],
    brackets: list[str],
) -> list[dict]:
    """
    Convert the dict returned by get_hero_position_stats() into a list of
    hero dicts using the same field names as OpenDota /heroStats:
        pos1_win, pos1_pick, pos2_win, pos2_pick, ... pos5_win, pos5_pick
    """
    heroes = []
    for hid, positions in raw.items():
        entry: dict = {"id": hid}
        for role_id in range(1, 6):
            pd = positions.get(role_id, {})
            entry[f"pos{role_id}_win"]  = pd.get("win",  0)
            entry[f"pos{role_id}_pick"] = pd.get("pick", 0)
        heroes.append(entry)
    return heroes


def merge_with_opendota(
    stratz_heroes: list[dict],
    opendota_heroes: list[dict],
) -> list[dict]:
    """
    Produce a merged hero list.

    For each hero x position:
      - Use Stratz win rate when pick >= MIN_PICKS  (bracket-specific, more relevant)
      - Fall back to OpenDota global win rate otherwise

    Returns a list in the same pos{n}_win / pos{n}_pick format.
    """
    od_by_id: dict[int, dict] = {h["id"]: h for h in opendota_heroes}
    sz_by_id: dict[int, dict] = {h["id"]: h for h in stratz_heroes}
    all_ids = set(od_by_id) | set(sz_by_id)
    merged: list[dict] = []

    for hid in sorted(all_ids):
        od = od_by_id.get(hid, {})
        sz = sz_by_id.get(hid, {})
        entry: dict = {"id": hid}
        for r in range(1, 6):
            sz_pick = sz.get(f"pos{r}_pick", 0)
            if sz_pick >= MIN_PICKS:
                entry[f"pos{r}_win"]  = sz[f"pos{r}_win"]
                entry[f"pos{r}_pick"] = sz_pick
            else:
                entry[f"pos{r}_win"]  = od.get(f"pos{r}_win",  0)
                entry[f"pos{r}_pick"] = od.get(f"pos{r}_pick", 0)
        merged.append(entry)

    return merged
