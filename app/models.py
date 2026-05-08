"""
Pydantic response models for the tracker API.
"""

from pydantic import BaseModel
from typing import Any


# ------------------------------------------------------------------ #
# Player
# ------------------------------------------------------------------ #

class PlayerProfile(BaseModel):
    account_id: int
    personaname: str | None = None
    avatarfull: str | None = None
    rank_tier: int | None = None
    mmr_estimate: dict | None = None
    profile: dict | None = None


class WinLoss(BaseModel):
    win: int
    lose: int
    winrate: float


class RecentMatch(BaseModel):
    match_id: int
    player_slot: int
    radiant_win: bool
    duration: int
    game_mode: int
    hero_id: int
    start_time: int
    kills: int
    deaths: int
    assists: int
    xp_per_min: int
    gold_per_min: int
    hero_damage: int
    tower_damage: int
    hero_healing: int
    last_hits: int
    lane: int | None = None
    lane_role: int | None = None
    is_roaming: bool | None = None

    @property
    def won(self) -> bool:
        is_radiant = self.player_slot < 128
        return self.radiant_win if is_radiant else not self.radiant_win

    @property
    def kda(self) -> float:
        return round((self.kills + self.assists) / max(self.deaths, 1), 2)


class HeroStat(BaseModel):
    hero_id: int
    last_played: int
    games: int
    win: int
    with_games: int
    with_win: int
    against_games: int
    against_win: int

    @property
    def winrate(self) -> float:
        return round(self.win / self.games * 100, 1) if self.games else 0.0


# ------------------------------------------------------------------ #
# Dashboard (aggregated view)
# ------------------------------------------------------------------ #

class FriendSummary(BaseModel):
    account_id: int
    label: str | None = None          # nickname from friends.json
    personaname: str | None = None
    avatarfull: str | None = None
    rank_tier: int | None = None
    wins: int
    losses: int
    winrate: float

    # Tier 1 — aggregates from recent matches
    avg_kda: float = 0.0
    avg_gpm: float = 0.0
    avg_xpm: float = 0.0
    recent_form: list[bool] = []      # True=win, most recent first
    current_streak: int = 0           # positive = win streak, negative = loss streak

    # Tier 2 — computed from recentMatches (no extra API calls)
    avg_hero_damage_per_min: float = 0.0
    avg_last_hits_per_min: float = 0.0
    avg_tower_damage: float = 0.0
    kda_std: float = 0.0              # KDA std dev — lower = more consistent
    gpm_std: float = 0.0              # GPM std dev
    hero_pool_size: int = 0           # distinct heroes in last 20 matches
    role_stats: dict = {}             # {"Carry": {"games": N, "wins": N, "winrate": X}}
    duration_stats: dict = {}         # {"<30min": {games, wins, winrate}, …}

    recent_matches: list[dict] = []
    top_heroes: list[dict] = []       # top 5 by games played


class DashboardResponse(BaseModel):
    friends: list[FriendSummary]


# ------------------------------------------------------------------ #
# Friends management
# ------------------------------------------------------------------ #

class Friend(BaseModel):
    account_id: int
    label: str | None = None        # Optional nickname
    steam_id_64: int | None = None  # Original 64-bit Steam ID (for reference)


class FriendsConfig(BaseModel):
    friends: list[Friend]


class AddFriendRequest(BaseModel):
    account_id: int
    label: str | None = None


class MessageResponse(BaseModel):
    message: str
    data: Any = None


# ------------------------------------------------------------------ #
# Win probability — request / response models
# ------------------------------------------------------------------ #

from pydantic import Field, model_validator


class PlayerSlotRequest(BaseModel):
    account_id: int | None = None   # None = untracked / random opponent
    hero_id: int
    role: int = Field(ge=1, le=5)
    is_radiant: bool


class DraftRequest(BaseModel):
    players: list[PlayerSlotRequest]

    @model_validator(mode="after")
    def validate_draft(self) -> "DraftRequest":
        if len(self.players) != 10:
            raise ValueError(f"Draft must have exactly 10 players, got {len(self.players)}")
        n_rad = sum(1 for p in self.players if p.is_radiant)
        if n_rad != 5:
            raise ValueError(f"Draft must have exactly 5 radiant players, got {n_rad}")
        return self


class PlayerPredictionResponse(BaseModel):
    label: str
    hero_id: int
    role: int
    baseline_wr: float
    fit_path: str
    player_score: float
    hero_delta_adj: float
    role_delta_adj: float
    hero_role_delta_adj: float | None
    form_delta: float


class SynergyEntryResponse(BaseModel):
    player_a: str
    player_b: str
    raw_delta: float
    n: int
    adjusted: float


class TeamPredictionResponse(BaseModel):
    players: list[PlayerPredictionResponse]
    synergy_entries: list[SynergyEntryResponse]
    synergy_total: float
    meta_score: float
    team_score: float


class FactorResponse(BaseModel):
    label: str
    signal: str
    value: float


class PredictionResponse(BaseModel):
    radiant: TeamPredictionResponse
    dire: TeamPredictionResponse
    matchup_total: float
    matchup_coverage: float
    radiant_score: float
    dire_score: float
    score_diff: float
    win_probability_radiant: float
    confidence: str
    top_factors: list[FactorResponse]
