"""
Win probability model for the Dota 2 Tracker.

Tiered additive scoring model:
  P(radiant wins) = sigmoid( (radiant_score - dire_score) / T )

Data sources loaded at startup (all optional -- model degrades gracefully):
  data/diff_player_x_hero.parquet    -> hero fit deltas per player        (A2)
  data/diff_player_x_role.parquet    -> role fit deltas per player        (A3)
  data/diff_player_x_player.parquet  -> teammate synergy deltas           (B)
  data/player_role_stats.json        -> heroxrole conditional win rates   (A4)
  data/hero_matchups.json            -> pairwise hero matchup edges       (C)
  data/hero_global_stats.json        -> global hero win rates by position (D)
  data/match_cache/                  -> recent form, last 20 matches      (A5)
  data/model_weights.json            -> calibrated weights + temperature T
"""

import json
import math
import pickle
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.config import ROOT_DIR

DATA_DIR     = ROOT_DIR / "data"
CACHE_DIR    = ROOT_DIR / "notebook_cache"
FRIENDS_FILE = ROOT_DIR / "friends.json"
WEIGHTS_FILE = DATA_DIR / "model_weights.json"

ROLE_ID_TO_NAME: dict[int, str] = {
    1: "Carry", 2: "Mid", 3: "Offlane", 4: "Jungle", 5: "Support"
}
ROLE_NAME_TO_ID: dict[str, int] = {v: k for k, v in ROLE_ID_TO_NAME.items()}

# Default weights -- overridden by data/model_weights.json when calibration has run.
DEFAULT_WEIGHTS: dict[str, float] = {
    "w_A4":  1.0,   # heroxrole conditional fit (replaces A2+A3 when n>=3)
    "w_A2":  0.8,   # hero fit alone
    "w_A3":  0.7,   # role fit alone
    "w_A5":  0.3,   # recent form
    "w_B":   0.5,   # teammate synergy (per pair, summed)
    "w_C":   0.6,   # hero matchup aggregate
    "w_D":   0.25,  # global meta signal
    "T":     12.0,  # sigmoid temperature -- higher = flatter curve
}

# Shrinkage constants k: adjusted = raw x n / (n + k)
K_HERO       = 15
K_ROLE       = 10
K_HERO_ROLE  = 5
K_SYNERGY    = 8
# Form uses a fixed half-weight (n=20, k=20 -> n/(n+k)=0.5) regardless of sample size.

# Role-pair weights for matchup scoring.
# Direct lane opponents matter most; cross-role pairings are secondary.
_ROLE_PAIR_WEIGHT: dict[tuple[int, int], float] = {
    (1, 1): 3.0, (2, 2): 3.0, (3, 3): 3.0, (4, 4): 3.0, (5, 5): 3.0,
    (1, 3): 1.0, (3, 1): 1.0, (1, 5): 1.0, (5, 1): 1.0,
    (3, 5): 1.0, (5, 3): 1.0,
    (2, 1): 1.0, (1, 2): 1.0, (2, 3): 1.0, (3, 2): 1.0,
    (2, 4): 0.5, (4, 2): 0.5, (2, 5): 0.5, (5, 2): 0.5,
    (4, 1): 0.5, (1, 4): 0.5, (4, 3): 0.5, (3, 4): 0.5,
    (4, 5): 0.5, (5, 4): 0.5,
}


# -- Input / output types ------------------------------------------------------

@dataclass
class PlayerSlot:
    """One player-hero-role assignment on a team."""
    account_id: int | None  # None = untracked random player
    hero_id: int
    role: int               # 1-5
    is_radiant: bool


@dataclass
class PlayerPrediction:
    """All Tier A signal values for one player slot, plus the aggregated score."""
    account_id: int | None
    label: str
    hero_id: int
    role: int
    is_radiant: bool

    # A1 -- career baseline win rate
    baseline_wr: float

    # A2 -- hero fit (personal hero history vs career average)
    hero_delta_raw: float   # raw delta before shrinkage
    hero_delta_n: int       # number of games on this hero
    hero_delta_adj: float   # after shrinkage (or global meta prior when n=0)

    # A3 -- role fit (personal role history vs career average)
    role_delta_raw: float
    role_delta_n: int
    role_delta_adj: float

    # A4 -- hero x role conditional (supersedes A2+A3 when n >= 3)
    hero_role_delta_raw: float | None   # None if data unavailable
    hero_role_n: int
    hero_role_delta_adj: float | None

    # A5 -- recent form (already half-shrunk: 20/(20+20)=0.5)
    form_delta: float

    # Which fit path was selected: "A4" when hero_role_n >= 3, else "A2+A3"
    fit_path: str

    # Total Tier A contribution (A1 + fit + form)
    player_score: float


@dataclass
class SynergyEntry:
    """Win-rate lift for one tracked friend pair on the same team."""
    player_a:  str
    player_b:  str
    raw_delta: float   # symmetrised average of both directional deltas
    n:         int     # minimum of the two directional game counts
    adjusted:  float   # after shrinkage k=8, weighted by w_B


@dataclass
class TeamSynergy:
    """All synergy contributions for one team."""
    entries: list[SynergyEntry]
    total:   float   # sum of entry.adjusted (already weight-applied)


@dataclass
class MatchupEntry:
    """Single hero vs hero matchup contribution."""
    radiant_hero_id: int
    dire_hero_id:    int
    radiant_role:    int
    dire_role:       int
    edge:            float   # P(radiant hero beats dire hero) - 0.5
    role_weight:     float   # from _ROLE_PAIR_WEIGHT
    contribution:    float   # edge * role_weight (pre-normalisation)


@dataclass
class MatchupResult:
    """Aggregated matchup signal for one team pair."""
    entries:  list[MatchupEntry]
    total:    float   # normalised, w_C applied
    coverage: float  # fraction of the 30.0 max role-weight covered


@dataclass
class Factor:
    """One named contribution to the net radiant score advantage."""
    label:  str    # human-readable name, e.g. "Sherry (radiant)"
    signal: str    # tier: "A2+A3", "A4", "B", "C", "D"
    value:  float  # positive = helps radiant, negative = helps dire


@dataclass
class TeamPrediction:
    """Full signal breakdown for one team."""
    players:    list["PlayerPrediction"]
    synergy:    "TeamSynergy"
    meta_score: float   # Tier D contribution (w_D already applied)
    team_score: float   # sum of player_scores + synergy.total + meta_score


@dataclass
class PredictionResult:
    """Complete output of WinProbabilityModel.predict()."""
    radiant:                 TeamPrediction
    dire:                    TeamPrediction
    matchup:                 MatchupResult
    radiant_score:           float   # radiant team_score + matchup.total
    dire_score:              float   # dire team_score
    score_diff:              float   # radiant_score - dire_score
    win_probability_radiant: float   # sigmoid(score_diff / T)
    confidence:              str     # "high" | "medium" | "low"
    top_factors:             list[Factor]


# -- Load-time diagnostics -----------------------------------------------------

@dataclass
class LoadSummary:
    baselines:   bool = False
    hero_deltas: bool = False
    role_deltas: bool = False
    teammate:    bool = False
    hero_role:   bool = False
    matchup:     bool = False
    meta:        bool = False
    form:        bool = False
    weights:     bool = False


# -- Main model class ----------------------------------------------------------

class WinProbabilityModel:
    """
    Loads all available data sources at construction time and exposes
    `predict(radiant_slots, dire_slots) -> PredictionResult`.

    Every data source is optional -- missing files produce a warning and the
    corresponding signal is zeroed out. The model always returns a result.
    """

    def __init__(self) -> None:
        # {account_id: {hero_id: {"delta": float, "n": int}}}
        self.hero_deltas: dict[int, dict[int, dict]] = {}
        # {account_id: {role_name: {"delta": float, "n": int}}}
        self.role_deltas: dict[int, dict[str, dict]] = {}
        # {account_id: {account_id: {"delta": float, "n": int}}}
        self.teammate_deltas: dict[int, dict[int, dict]] = {}
        # {account_id: {role_id: {hero_id: {"wr": float, "n": int}}}}
        self.hero_role_stats: dict[int, dict[int, dict[int, dict]]] = {}
        # {hero_id: {hero_id: float}}  edge = P(attacker beats defender) - 0.5
        self.matchup_matrix: dict[int, dict[int, float]] = {}
        # {hero_id: {role_id: float}}  global win-rate at position - 50.0
        self.global_meta: dict[int, dict[int, float]] = {}
        # {account_id: float}  (last_20_wr - career_baseline) x 0.5  (half-shrunk)
        self.form_deltas: dict[int, float] = {}
        # {account_id: float}  career win rate %
        self.baselines: dict[int, float] = {}
        # {account_id: str}
        self.labels: dict[int, str] = {}

        self.weights: dict[str, float] = dict(DEFAULT_WEIGHTS)
        self.summary = LoadSummary()

    # -- Public factory --------------------------------------------------------

    @classmethod
    def load(cls) -> "WinProbabilityModel":
        """Load all data sources and return a ready model instance."""
        model = cls()
        model._load_friends()
        model._load_baselines()
        model._load_hero_deltas()
        model._load_role_deltas()
        model._load_teammate_deltas()
        model._load_hero_role_stats()
        model._load_matchup_matrix()
        model._load_global_meta()
        model._load_form()
        model._load_weights()
        model._print_summary()
        return model

    # -- Static helpers --------------------------------------------------------

    @staticmethod
    def _shrink(delta: float, n: int, k: int) -> float:
        """James-Stein shrinkage toward 0.  adjusted = delta x n / (n + k)."""
        if n <= 0:
            return 0.0
        return delta * n / (n + k)

    # -- Tier A: per-player fit ------------------------------------------------

    def _score_player(self, slot: PlayerSlot) -> PlayerPrediction:
        """
        Compute all Tier A signals for one player-hero-role assignment.

        Signal selection:
          - A4 (hero x role conditional) is used when n >= 3; it already encodes
            both hero affinity and role comfort, so A2+A3 are skipped.
          - When A4 is unavailable, A2 and A3 are computed independently.
          - For untracked players (account_id=None) all deltas are zero;
            only the global 50.0 baseline contributes.
        """
        aid      = slot.account_id
        hero_id  = slot.hero_id
        role_id  = slot.role
        role_name = ROLE_ID_TO_NAME.get(role_id, "Carry")
        label    = (self.labels.get(aid, f"Player {aid}") if aid else "Unknown")
        w        = self.weights

        # A1 -- career baseline
        baseline = self.baselines.get(aid, 50.0) if aid else 50.0

        # A2 -- hero fit
        hero_entry = (
            self.hero_deltas.get(aid, {}).get(hero_id)
            if aid else None
        )
        if hero_entry:
            hero_delta_raw = hero_entry["delta"]
            hero_delta_n   = hero_entry["n"]
            hero_delta_adj = self._shrink(hero_delta_raw, hero_delta_n, K_HERO)
        else:
            # No personal hero history -- signal is zero; Tier D handles global meta.
            hero_delta_raw = 0.0
            hero_delta_n   = 0
            hero_delta_adj = 0.0

        # A3 -- role fit
        role_entry = (
            self.role_deltas.get(aid, {}).get(role_name)
            if aid else None
        )
        if role_entry:
            role_delta_raw = role_entry["delta"]
            role_delta_n   = role_entry["n"]
            role_delta_adj = self._shrink(role_delta_raw, role_delta_n, K_ROLE)
        else:
            role_delta_raw = 0.0
            role_delta_n   = 0
            role_delta_adj = 0.0

        # A4 -- hero x role conditional
        hero_role_delta_raw: float | None = None
        hero_role_n   = 0
        hero_role_delta_adj: float | None = None

        if aid:
            hr_entry = (
                self.hero_role_stats
                    .get(aid, {})
                    .get(role_id, {})
                    .get(hero_id)
            )
            if hr_entry and hr_entry["n"] >= 3:
                hero_role_delta_raw = hr_entry["wr"] - baseline
                hero_role_n         = hr_entry["n"]
                hero_role_delta_adj = self._shrink(
                    hero_role_delta_raw, hero_role_n, K_HERO_ROLE
                )

        # A5 -- recent form (loaded pre-shrunk at 0.5 weight)
        form_delta = self.form_deltas.get(aid, 0.0) if aid else 0.0

        # Select fit path: A4 supersedes A2+A3 when sufficient data exists
        if hero_role_delta_adj is not None:
            fit_contribution = w["w_A4"] * hero_role_delta_adj
            fit_path = "A4"
        else:
            fit_contribution = (
                w["w_A2"] * hero_delta_adj
                + w["w_A3"] * role_delta_adj
            )
            fit_path = "A2+A3"

        player_score = baseline + fit_contribution + w["w_A5"] * form_delta

        return PlayerPrediction(
            account_id       = aid,
            label            = label,
            hero_id          = hero_id,
            role             = role_id,
            is_radiant       = slot.is_radiant,
            baseline_wr      = round(baseline, 2),
            hero_delta_raw   = round(hero_delta_raw, 2),
            hero_delta_n     = hero_delta_n,
            hero_delta_adj   = round(hero_delta_adj, 2),
            role_delta_raw   = round(role_delta_raw, 2),
            role_delta_n     = role_delta_n,
            role_delta_adj   = round(role_delta_adj, 2),
            hero_role_delta_raw = (
                round(hero_role_delta_raw, 2)
                if hero_role_delta_raw is not None else None
            ),
            hero_role_n      = hero_role_n,
            hero_role_delta_adj = (
                round(hero_role_delta_adj, 2)
                if hero_role_delta_adj is not None else None
            ),
            form_delta       = round(form_delta, 2),
            fit_path         = fit_path,
            player_score     = round(player_score, 2),
        )

    # -- Tier B: teammate synergy ----------------------------------------------

    def _synergy_score(self, player_ids: list[Optional[int]]) -> TeamSynergy:
        """
        Compute synergy bonuses for all pairs of tracked friends on one team.

        Only pairs where BOTH directional records exist and the minimum
        game count >= 5 contribute.  Missing data is safely skipped.
        """
        tracked = [
            aid for aid in player_ids
            if aid is not None and aid in self.labels
        ]
        entries: list[SynergyEntry] = []
        w = self.weights["w_B"]

        for i in range(len(tracked)):
            for j in range(i + 1, len(tracked)):
                a, b = tracked[i], tracked[j]
                d_ab = self.teammate_deltas.get(a, {}).get(b)
                d_ba = self.teammate_deltas.get(b, {}).get(a)

                # Collect whichever directional records exist
                available = [d for d in (d_ab, d_ba) if d is not None]
                if not available:
                    continue

                # Symmetrise: average of available directions
                raw = sum(d["delta"] for d in available) / len(available)
                # Conservative: use the minimum game count for shrinkage
                n   = min(d["n"] for d in available)

                if n < 5:
                    continue  # too few joint games to trust this pair

                adj = self._shrink(raw, n, K_SYNERGY) * w
                entries.append(SynergyEntry(
                    player_a  = self.labels[a],
                    player_b  = self.labels[b],
                    raw_delta = round(raw, 2),
                    n         = n,
                    adjusted  = round(adj, 2),
                ))

        total = sum(e.adjusted for e in entries)
        return TeamSynergy(entries=entries, total=round(total, 2))

    def _matchup_score(
        self,
        radiant_slots: list["PlayerSlot"],
        dire_slots:    list["PlayerSlot"],
    ) -> "MatchupResult":
        """
        Tier C: hero matchup signal.

        For every (radiant_slot, dire_slot) pair we look up the head-to-head
        edge from the matchup matrix, weight it by the role-pair importance, and
        normalise by the total weight of pairs we actually found data for.

        Returns a MatchupResult whose `total` is in the same additive-score
        space as the other signals (w_C already applied).
        """
        w = self.weights.get("w_C", DEFAULT_WEIGHTS["w_C"])

        entries: list[MatchupEntry] = []
        weight_sum = 0.0

        for r_slot in radiant_slots:
            for d_slot in dire_slots:
                h_r, h_d = r_slot.hero_id, d_slot.hero_id
                r_role, d_role = r_slot.role, d_slot.role

                if h_r is None or h_d is None:
                    continue

                # matchup_matrix[h_r][h_d] = P(h_r wins) - 0.5  (radiant perspective)
                edge = self.matchup_matrix.get(h_r, {}).get(h_d)
                if edge is None:
                    continue

                rw = _ROLE_PAIR_WEIGHT.get((r_role, d_role), 0.0)
                if rw == 0.0:
                    continue

                contrib = edge * rw
                entries.append(MatchupEntry(
                    radiant_hero_id = h_r,
                    dire_hero_id    = h_d,
                    radiant_role    = r_role,
                    dire_role       = d_role,
                    edge            = round(edge, 4),
                    role_weight     = rw,
                    contribution    = round(contrib, 4),
                ))
                weight_sum += rw

        MAX_WEIGHT = 30.0  # sum of all 25 role-pair weights when coverage is 100%
        coverage = weight_sum / MAX_WEIGHT

        if weight_sum > 0:
            weighted_avg = sum(e.contribution for e in entries) / weight_sum
            total = round(w * weighted_avg, 3)
        else:
            total = 0.0

        return MatchupResult(entries=entries, total=total, coverage=round(coverage, 3))

    def _meta_score(self, slots: list[PlayerSlot]) -> float:
        """
        Tier D: global hero win rate at the assigned position (vs 50 % baseline).

        Summed over all 5 slots, multiplied by w_D.
        Uses the merged Stratz+OpenDota data when available.
        """
        w = self.weights.get("w_D", DEFAULT_WEIGHTS["w_D"])
        total = 0.0
        for slot in slots:
            if slot.hero_id is None:
                continue
            delta = self.global_meta.get(slot.hero_id, {}).get(slot.role, 0.0)
            total += delta
        return round(w * total, 3)

    def predict(
        self,
        radiant: list[PlayerSlot],
        dire: list[PlayerSlot],
    ) -> PredictionResult:
        """
        Full prediction for a 10-player draft.

        Calls all four tier scorers and combines into a single sigmoid probability.
        Every signal degrades gracefully: missing data produces zero contribution,
        not an error.
        """
        T = self.weights.get("T", DEFAULT_WEIGHTS["T"])

        # -- Tier A: per-player fit + form ------------------------------------
        r_players = [self._score_player(s) for s in radiant]
        d_players = [self._score_player(s) for s in dire]

        # -- Tier B: teammate synergy ----------------------------------------
        r_synergy = self._synergy_score([s.account_id for s in radiant])
        d_synergy = self._synergy_score([s.account_id for s in dire])

        # -- Tier C: hero matchup (radiant perspective) ----------------------
        matchup = self._matchup_score(radiant, dire)

        # -- Tier D: global meta ---------------------------------------------
        r_meta = self._meta_score(radiant)
        d_meta = self._meta_score(dire)

        # -- Aggregate team scores -------------------------------------------
        r_team = sum(p.player_score for p in r_players) + r_synergy.total + r_meta
        d_team = sum(p.player_score for p in d_players) + d_synergy.total + d_meta

        # matchup.total is already the radiant advantage from hero counters
        r_final    = round(r_team + matchup.total, 3)
        d_final    = round(d_team, 3)
        score_diff = round(r_final - d_final, 3)

        # -- Win probability (sigmoid) ---------------------------------------
        # Clamp to avoid overflow on extreme drafts
        clamped  = max(min(score_diff / T, 500.0), -500.0)
        win_prob = round(1.0 / (1.0 + math.exp(-clamped)), 4)

        # -- Confidence rating -----------------------------------------------
        n_active = sum([
            self.summary.baselines,
            self.summary.hero_deltas,
            self.summary.role_deltas,
            self.summary.hero_role,
            self.summary.teammate,
            self.summary.matchup,
            self.summary.meta,
            self.summary.form,
        ])
        abs_diff = abs(score_diff)
        if n_active >= 6 and abs_diff >= 8.0:
            confidence = "high"
        elif n_active >= 4 and abs_diff >= 4.0:
            confidence = "medium"
        else:
            confidence = "low"

        # -- Top factors (net radiant advantage per signal) ------------------
        factors: list[Factor] = []

        for p in r_players:
            fit = p.player_score - p.baseline_wr   # fit + form above baseline
            if fit != 0.0:
                factors.append(Factor(
                    label  = f"{p.label} (radiant)",
                    signal = p.fit_path,
                    value  = round(fit, 2),
                ))

        for p in d_players:
            fit = p.player_score - p.baseline_wr
            if fit != 0.0:
                factors.append(Factor(
                    label  = f"{p.label} (dire)",
                    signal = p.fit_path,
                    value  = round(-fit, 2),   # dire fit advantage hurts radiant
                ))

        syn_net = r_synergy.total - d_synergy.total
        if syn_net != 0.0:
            factors.append(Factor(label="synergy", signal="B", value=round(syn_net, 2)))

        if matchup.total != 0.0:
            factors.append(Factor(label="hero matchup", signal="C", value=round(matchup.total, 2)))

        meta_net = r_meta - d_meta
        if meta_net != 0.0:
            factors.append(Factor(label="global meta", signal="D", value=round(meta_net, 2)))

        top_factors = sorted(factors, key=lambda f: abs(f.value), reverse=True)[:3]

        return PredictionResult(
            radiant                  = TeamPrediction(r_players, r_synergy, r_meta, round(r_team, 3)),
            dire                     = TeamPrediction(d_players, d_synergy, d_meta, round(d_team, 3)),
            matchup                  = matchup,
            radiant_score            = r_final,
            dire_score               = d_final,
            score_diff               = score_diff,
            win_probability_radiant  = win_prob,
            confidence               = confidence,
            top_factors              = top_factors,
        )

    # -- Data loaders ----------------------------------------------------------

    def _load_friends(self) -> None:
        if not FRIENDS_FILE.exists():
            warnings.warn("[probability] friends.json not found.")
            return
        with open(FRIENDS_FILE, encoding="utf-8") as fh:
            friends = json.load(fh)["friends"]
        self.labels = {f["account_id"]: f["label"] for f in friends}

    def _load_baselines(self) -> None:
        """
        Career win rate per player.  Priority order:
          1. data/baselines.json  (written manually or by a future helper)
          2. notebook_cache/{id}_wl.pkl  (written by notebook S2 api_get calls)
          3. data/match_cache player match lists  (200-match WR -- coarser proxy)
          4. Default 50.0 for all players
        """
        baselines_file = DATA_DIR / "baselines.json"
        if baselines_file.exists():
            with open(baselines_file, encoding="utf-8") as fh:
                raw = json.load(fh)
            self.baselines = {int(k): v for k, v in raw.items()}
            self.summary.baselines = True
            return

        # Notebook pickle cache: api_get("/players/{id}/wl") -> "players_{id}_wl.pkl"
        loaded = 0
        for aid in self.labels:
            pkl = CACHE_DIR / f"players_{aid}_wl.pkl"
            if pkl.exists():
                try:
                    with open(pkl, "rb") as fh:
                        wl = pickle.load(fh)
                    w, l = int(wl.get("win", 0)), int(wl.get("lose", 0))
                    if w + l > 0:
                        self.baselines[aid] = round(w / (w + l) * 100, 2)
                        loaded += 1
                except Exception:
                    pass
        if loaded > 0:
            self.summary.baselines = True
            return

        # Fall back to DEEP match list (200-match WR -- approximate but available)
        try:
            from app.match_cache import load_player_match_list
            for aid in self.labels:
                ml = load_player_match_list(aid)
                if not ml:
                    continue
                wins = sum(
                    1 for m in ml
                    if (m.get("player_slot", 0) < 128) == m.get("radiant_win", False)
                )
                self.baselines[aid] = round(wins / len(ml) * 100, 2)
            if self.baselines:
                self.summary.baselines = True
                return
        except Exception:
            pass

        warnings.warn(
            "[probability] No baseline win rates found -- defaulting all players to 50.0%. "
            "Run notebook S2 or create data/baselines.json to fix this."
        )

    def _load_hero_deltas(self) -> None:
        """A2: hero fit delta per player from diff_player_x_hero.parquet."""
        path = DATA_DIR / "diff_player_x_hero.parquet"
        if not path.exists():
            warnings.warn(
                "[probability] diff_player_x_hero.parquet missing -- A2 hero fit disabled. "
                "Run notebook S13."
            )
            return
        try:
            import pandas as pd
            df = pd.read_parquet(path)
            # Prefer account_id column (post-migration); fall back to label lookup
            # for older parquet files generated by an unmigrated notebook §13.
            if "account_id" in df.columns:
                for _, row in df.iterrows():
                    aid = int(row["account_id"])
                    self.hero_deltas.setdefault(aid, {})[int(row["hero_id"])] = {
                        "delta": float(row["delta"]),
                        "n":     int(row["games"]),
                    }
            else:
                label_to_aid = {v: k for k, v in self.labels.items()}
                for _, row in df.iterrows():
                    aid = label_to_aid.get(row["player"])
                    if aid is None:
                        continue
                    self.hero_deltas.setdefault(aid, {})[int(row["hero_id"])] = {
                        "delta": float(row["delta"]),
                        "n":     int(row["games"]),
                    }
            self.summary.hero_deltas = True
        except Exception as exc:
            warnings.warn(f"[probability] Failed to load hero deltas: {exc}")

    def _load_role_deltas(self) -> None:
        """A3: role fit delta per player from diff_player_x_role.parquet."""
        path = DATA_DIR / "diff_player_x_role.parquet"
        if not path.exists():
            warnings.warn(
                "[probability] diff_player_x_role.parquet missing -- A3 role fit disabled. "
                "Run notebook S13."
            )
            return
        try:
            import pandas as pd
            df = pd.read_parquet(path)
            if "account_id" in df.columns:
                for _, row in df.iterrows():
                    aid = int(row["account_id"])
                    self.role_deltas.setdefault(aid, {})[row["role"]] = {
                        "delta": float(row["delta"]),
                        "n":     int(row["games"]),
                    }
            else:
                label_to_aid = {v: k for k, v in self.labels.items()}
                for _, row in df.iterrows():
                    aid = label_to_aid.get(row["player"])
                    if aid is None:
                        continue
                    self.role_deltas.setdefault(aid, {})[row["role"]] = {
                        "delta": float(row["delta"]),
                        "n":     int(row["games"]),
                    }
            self.summary.role_deltas = True
        except Exception as exc:
            warnings.warn(f"[probability] Failed to load role deltas: {exc}")

    def _load_teammate_deltas(self) -> None:
        """B: teammate synergy delta per player pair from diff_player_x_player.parquet."""
        path = DATA_DIR / "diff_player_x_player.parquet"
        if not path.exists():
            warnings.warn(
                "[probability] diff_player_x_player.parquet missing -- Tier B synergy disabled. "
                "Run notebook S13."
            )
            return
        try:
            import pandas as pd
            df = pd.read_parquet(path)
            if "account_id" in df.columns and "with_account_id" in df.columns:
                for _, row in df.iterrows():
                    i = int(row["account_id"])
                    j = int(row["with_account_id"])
                    self.teammate_deltas.setdefault(i, {})[j] = {
                        "delta": float(row["delta"]),
                        "n":     int(row["games"]),
                    }
            else:
                label_to_aid = {v: k for k, v in self.labels.items()}
                for _, row in df.iterrows():
                    i = label_to_aid.get(row["player"])
                    j = label_to_aid.get(row["with_player"])
                    if i is None or j is None:
                        continue
                    self.teammate_deltas.setdefault(i, {})[j] = {
                        "delta": float(row["delta"]),
                        "n":     int(row["games"]),
                    }
            self.summary.teammate = True
        except Exception as exc:
            warnings.warn(f"[probability] Failed to load teammate deltas: {exc}")

    def _load_hero_role_stats(self) -> None:
        """A4: heroxrole conditional win rates from player_role_stats.json."""
        path = DATA_DIR / "player_role_stats.json"
        if not path.exists():
            warnings.warn(
                "[probability] player_role_stats.json missing -- A4 heroxrole fit disabled. "
                "Run: python cli.py refresh-data"
            )
            return
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            for aid_str, player_data in raw.get("players", {}).items():
                aid = int(aid_str)
                self.hero_role_stats[aid] = {}
                for role_id_str, role_data in player_data.get("roles", {}).items():
                    role_id = int(role_id_str)
                    self.hero_role_stats[aid][role_id] = {}
                    for h in role_data.get("heroes", []):
                        hid = int(h["hero_id"])
                        self.hero_role_stats[aid][role_id][hid] = {
                            "wr": float(h["winrate"]),
                            "n":  int(h["games"]),
                        }
            self.summary.hero_role = True
        except Exception as exc:
            warnings.warn(f"[probability] Failed to load heroxrole stats: {exc}")

    def _load_matchup_matrix(self) -> None:
        """
        C: pairwise hero matchup edges.

        Source: data/hero_matchups.json (OpenDota per-hero matchup endpoint)

        Both files use the same format:
            {matchups: {hero_id_str: [{hero_id, games_played, wins}, ...]}}
        """
        path = DATA_DIR / "hero_matchups.json"
        if not path.exists():
            warnings.warn(
                "[probability] hero_matchups.json missing -- Tier C matchup signals disabled. "
                "Run: python cli.py refresh-data"
            )
            return
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            for hero_id_str, matchups in raw.get("matchups", {}).items():
                h_a = int(hero_id_str)
                if not isinstance(matchups, list):
                    continue
                self.matchup_matrix[h_a] = {}
                for m in matchups:
                    h_b   = int(m.get("hero_id", 0))
                    games = int(m.get("games_played", 0))
                    wins  = int(m.get("wins", 0))
                    if h_b and games > 0:
                        self.matchup_matrix[h_a][h_b] = round(wins / games - 0.5, 4)
            self.summary.matchup = True
        except Exception as exc:
            warnings.warn(f"[probability] Failed to load matchup matrix: {exc}")

    def _load_global_meta(self) -> None:
        """
        D: global hero win rate at each position.

        Priority:
          1. data/hero_global_stats_merged.json  (Stratz + OpenDota, bracket-specific)
          2. data/hero_global_stats_stratz.json  (Stratz only)
          3. data/hero_global_stats.json         (OpenDota global aggregate)
        """
        candidates = [
            DATA_DIR / "hero_global_stats_merged.json",
            DATA_DIR / "hero_global_stats_stratz.json",
            DATA_DIR / "hero_global_stats.json",
        ]
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            warnings.warn(
                "[probability] No hero_global_stats file found -- Tier D meta disabled. "
                "Run: python cli.py refresh-data"
            )
            return
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            source = raw.get("source", "unknown")
            for hero in raw.get("heroes", []):
                hid = int(hero.get("id", 0))
                if not hid:
                    continue
                self.global_meta[hid] = {}
                for role_id in range(1, 6):
                    pick = hero.get(f"pos{role_id}_pick", 0) or 0
                    win  = hero.get(f"pos{role_id}_win",  0) or 0
                    if pick > 0:
                        self.global_meta[hid][role_id] = round(
                            win / pick * 100 - 50.0, 2
                        )
            self.summary.meta = True
            print(f"  [meta] loaded {path.name} (source={source}, {len(self.global_meta)} heroes)")
        except Exception as exc:
            warnings.warn(f"[probability] Failed to load global meta from {path.name}: {exc}")

    def _load_form(self) -> None:
        """A5: recent form delta from the DEEP match-list cache (newest 20 matches)."""
        try:
            from app.match_cache import load_player_match_list
            for aid, baseline in self.baselines.items():
                ml = load_player_match_list(aid)
                if not ml:
                    continue
                recent = ml[:20]
                wins = sum(
                    1 for m in recent
                    if (m.get("player_slot", 0) < 128) == m.get("radiant_win", False)
                )
                recent_wr = wins / len(recent) * 100
                # Fixed half-weight: n/(n+k) = 20/40 = 0.5
                self.form_deltas[aid] = round((recent_wr - baseline) * 0.5, 2)
            if self.form_deltas:
                self.summary.form = True
        except Exception as exc:
            warnings.warn(f"[probability] Failed to compute form deltas: {exc}")

    def _load_weights(self) -> None:
        if not WEIGHTS_FILE.exists():
            return  # silently use defaults -- calibration hasn't run yet
        try:
            with open(WEIGHTS_FILE, encoding="utf-8") as fh:
                saved = json.load(fh)
            self.weights.update(saved)
            self.summary.weights = True
        except Exception as exc:
            warnings.warn(f"[probability] Failed to load model_weights.json: {exc}")

    def save_weights(self, path: Optional[Path] = None) -> None:
        target = Path(path) if path else WEIGHTS_FILE
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(self.weights, fh, indent=2)

    def load_weights(self, path: Optional[Path] = None) -> None:
        target = Path(path) if path else WEIGHTS_FILE
        with open(target, encoding="utf-8") as fh:
            self.weights.update(json.load(fh))

    # -- Summary ---------------------------------------------------------------

    def _print_summary(self) -> None:
        s = self.summary
        tick = {True: "ok", False: "--"}
        parts = [
            f"baselines:{tick[s.baselines]}",
            f"hero_delta:{tick[s.hero_deltas]}",
            f"role_delta:{tick[s.role_deltas]}",
            f"hero_x_role:{tick[s.hero_role]}",
            f"teammate:{tick[s.teammate]}",
            f"matchup:{tick[s.matchup]}",
            f"meta:{tick[s.meta]}",
            f"form:{tick[s.form]}",
            f"weights:{tick[s.weights]}",
        ]
        print("[WinProbabilityModel] Loaded -- " + "  ".join(parts))
        n_hero_entries  = sum(len(v) for v in self.hero_deltas.values())
        n_matchup_pairs = sum(len(v) for v in self.matchup_matrix.values())
        print(
            f"  Tracked players: {len(self.baselines)}  |  "
            f"Hero-delta entries: {n_hero_entries}  |  "
            f"Matchup pairs: {n_matchup_pairs}"
        )


# Module-level singleton -- loaded once at server startup, reused across requests.
_model: Optional[WinProbabilityModel] = None


def get_model() -> WinProbabilityModel:
    global _model
    if _model is None:
        _model = WinProbabilityModel.load()
    return _model


def reset_model() -> WinProbabilityModel:
    """Force-reload from disk and replace the singleton. Call after refresh-data."""
    global _model
    _model = WinProbabilityModel.load()
    return _model
