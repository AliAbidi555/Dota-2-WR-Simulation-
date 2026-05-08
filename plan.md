# Win Probability Model — Implementation Plan

## Status Legend
- `[ ]` Not started
- `[→]` In progress
- `[x]` Complete

---

## Overview

A tiered additive scoring model that predicts `P(radiant wins)` given a 10-player draft. Each tracked friend contributes multiple signals derived from their personal history. Scores are summed per team, differenced, and passed through a sigmoid with a calibrated temperature.

```
P(radiant wins) = sigmoid( (radiant_score − dire_score) / T )
```

### Files to be created
| File | Purpose |
|---|---|
| `app/probability.py` | `WinProbabilityModel` class — all signal logic, no FastAPI |
| `app/routes/probability.py` | FastAPI router: `POST /probability/predict`, `GET /probability/calibrate` |
| `data/model_weights.json` | Calibrated weights + temperature T (written by §14) |
| Notebook §14 | Feature engineering on DEEP cache, logistic regression fit, calibration curve |
| `static/dashboard.html` additions | Draft input panel, live WR bar, signal breakdown accordion |

### Data sources consumed
| File | What it provides |
|---|---|
| `diff_player_x_hero.parquet` | `delta_hero[player][hero]` = hero_wr − baseline_wr, n games |
| `diff_player_x_role.parquet` | `delta_role[player][role]` = role_wr − baseline_wr, n games |
| `diff_player_x_player.parquet` | `delta_teammate[i][j]` = with_wr − baseline_wr, n games |
| `player_role_stats.json` | `hero_role_wr[player][role][hero]` = WR on hero *within* role |
| `hero_matchups.json` | `matchup_edge[h_a][h_b]` = P(h_a beats h_b) − 0.5 |
| `hero_global_stats.json` | `meta_wr[hero][role]` = global win rate at that position |
| `data/hero_global_stats_stratz.json` | Bracket-specific hero meta from Stratz |
| `data/hero_global_stats_merged.json` | Stratz + OpenDota merged meta (preferred by model) |
| DEEP / `data/match_cache/` | Recent form (last 20 matches), hero×role cross-check |
| `friends.json` | account_id list + labels |

---

## Signal Inventory

### Tier A — Per-player fit (computed per player slot)

| Signal | Formula | Source | Shrinkage k |
|---|---|---|---|
| A1 Career baseline | `career_wins / (wins+losses) × 100` | `wl` endpoint | none |
| A2 Hero fit | `hero_wr − baseline_wr` | `diff_player_x_hero.parquet` | 15 |
| A3 Role fit | `role_wr − baseline_wr` | `diff_player_x_role.parquet` | 10 |
| A4 Hero×Role fit | `hero_role_wr(hero,role) − baseline_wr` | `player_role_stats.json` | 5 |
| A5 Recent form | `last_20_wr − baseline_wr` | DEEP cache | 20 (fixed) |

**Interaction rule:** when A4 has n ≥ 3, it *replaces* A2+A3 (not added — they are already encoded inside A4).

Shrinkage formula: `adjusted = raw_delta × n / (n + k)`

When hero has no player history (n=0 for A2): substitute `meta_wr[hero][role] − 50.0` as a weak prior.

### Tier B — Teammate synergy

For each pair of tracked friends on the same team with n ≥ 5 games together:
```
synergy[i,j] = (delta_teammate[i→j] + delta_teammate[j→i]) / 2    # symmetrize
adjusted = synergy × n / (n + 8)                                    # shrinkage k=8
team_synergy = Σ adjusted(i,j) for all friend pairs on team
```
Source: `diff_player_x_player.parquet`.

### Tier C — Hero matchup matrix

For each (radiant_hero, dire_hero) pair:
```
edge[h_r][h_d] = wins_h_r_vs_h_d / games_h_r_vs_h_d − 0.5
```
Aggregated with role-weighted pairings:
- Direct lane opponents (same role): weight **3.0**
- Adjacent role pairings: weight **1.0**
- Off-lane support cross-matchups: weight **0.5**

```
matchup_score = Σ role_weight[r_r, r_d] × edge[hero_r[r_r]][hero_d[r_d]]
```
Falls back to unweighted mean of all 25 pairings if roles are unknown.
Source: `hero_matchups.json`.

### Tier D — Global meta signal

```
meta_delta[hero][role] = pos{role}_win / pos{role}_pick × 100 − 50.0
team_meta = Σ meta_delta[hero][role] per player slot
```
Source: `hero_global_stats.json`.

---

## Scoring Formula (full)

```
team_score =
  Σ over tracked players:
    A1: baseline[p]
  + A4_or_(A2+A3): adjusted hero×role delta (or hero+role separate)
  + w_A5 × adjusted_form[p]

  + w_B × team_synergy_score
  + w_C × matchup_score
  + w_D × team_meta_score

P(radiant) = sigmoid( (radiant_score − dire_score) / T )
```

Default weights before calibration:
```json
{
  "w_A4":  1.0,
  "w_A2":  0.8,
  "w_A3":  0.7,
  "w_A5":  0.3,
  "w_B":   0.5,
  "w_C":   0.6,
  "w_D":   0.25,
  "T":     12.0
}
```

---

## Output: PredictionResult (JSON)

```json
{
  "win_probability_radiant": 0.63,
  "confidence": "high",
  "radiant_score": 54.2,
  "dire_score":   49.1,
  "radiant": {
    "players": [
      {
        "label": "Rafay", "hero": "Invoker", "role": "Mid",
        "baseline_wr": 51.2,
        "hero_role_delta": 9.1, "hero_role_n": 18,
        "form_delta": 3.5,
        "contribution": 12.6
      }
    ],
    "synergy_bonus": 3.8,
    "matchup_score": 1.4,
    "meta_score": 0.8
  },
  "dire": { "..." },
  "top_factors": [
    "Rafay is +9.1% on Invoker mid (18 games)",
    "Haseeb+Abidi have +8.4% WR together (31 games)",
    "Earthshaker hard-counters Magnus (+6.2% matchup edge)"
  ]
}
```

`confidence`:
- **high** — ≥4 tracked players per team, min hero-history n ≥ 10
- **medium** — ≥2 tracked players per team, some signals missing
- **low** — <2 tracked players per team or heavy reliance on global priors

---

## Implementation Steps

### Step 1 — Data loading layer  `[x]`
**File:** `app/probability.py` (skeleton + loaders only)

Create `WinProbabilityModel` class with:
- `__init__`: load all 5 data sources into clean Python dicts at startup
- `_load_hero_deltas()` — parses `diff_player_x_hero.parquet` → `dict[account_id][hero_id] = {delta, n}`
- `_load_role_deltas()` — parses `diff_player_x_role.parquet` → `dict[account_id][role_name] = {delta, n}`
- `_load_teammate_deltas()` — parses `diff_player_x_player.parquet` → `dict[account_id][account_id] = {delta, n}`
- `_load_hero_role_stats()` — parses `player_role_stats.json` → `dict[account_id][role_id][hero_id] = {wr, n}`
- `_load_matchup_matrix()` — parses `hero_matchups.json` → `dict[hero_id][hero_id] = edge`
- `_load_global_meta()` — parses `hero_global_stats.json` → `dict[hero_id][role] = meta_delta`
- `_load_form()` — reads DEEP match cache via `match_cache.load_player_match_list` + `load_match` → `dict[account_id] = last_20_wr`
- `_load_baselines()` — reads `friends.json` + per-player `wl` from notebook cache or API

Expose `WinProbabilityModel.load() -> WinProbabilityModel` classmethod that loads everything and returns a ready instance. Log a warning (not error) for each data source that is missing — model degrades gracefully.

Also add `_shrink(delta, n, k) -> float` static helper.

**Done when:** `model = WinProbabilityModel.load()` runs without error and prints a summary of which sources loaded.

---

### Step 2 — Tier A signals (player fit)  `[x]`
**File:** `app/probability.py` (add to existing class)

Add `PlayerSlot` dataclass:
```python
@dataclass
class PlayerSlot:
    account_id: int | None   # None = untracked
    hero_id: int
    role: int                # 1–5
    is_radiant: bool
```

Add `_score_player(slot: PlayerSlot) -> PlayerPrediction` which returns:
- `baseline_wr` (A1)
- `hero_delta`, `hero_n` (A2, shrunk)
- `role_delta`, `role_n` (A3, shrunk)
- `hero_role_delta`, `hero_role_n` (A4, shrunk) — set to `(None, 0)` if < 3 games
- `form_delta` (A5, always half-weight)
- `player_score` = A1 + effective_fit + form_contribution

Logic: if `hero_role_n >= 3` → use A4, skip A2+A3. Else use A2+A3 separately.

Untracked players (account_id=None): baseline=50.0, all deltas=0, form=0, meta prior for A2.

**Done when:** unit-testable standalone — given a mock slot with known hero/role, returns expected score.

---

### Step 3 — Tier B: teammate synergy  `[x]`
**File:** `app/probability.py`

Add `_synergy_score(player_ids: list[int | None]) -> float` which:
- Filters to tracked players only
- For each pair (i, j) with n ≥ 5 games together in the parquet data:
  - Symmetrizes: `(delta[i→j] + delta[j→i]) / 2`
  - Applies shrinkage k=8
- Returns sum of all adjusted pair bonuses

**Done when:** returns correct values for known friend pairs from `diff_player_x_player.parquet`.

---

### Step 4 — Tier C: hero matchup matrix  `[x]`
**File:** `app/probability.py`

Add `_matchup_score(radiant_slots: list[PlayerSlot], dire_slots: list[PlayerSlot]) -> float` which:
- For each (radiant_slot, dire_slot) pair:
  - Looks up `edge[h_r][h_d]` from matchup matrix
  - Applies role weight (3.0 same role, 1.0 adjacent, 0.5 cross)
- Returns normalised aggregate (divide total by sum of weights so score is in % units)

Fallback: if a matchup pair isn't in `hero_matchups.json`, skip it (sparse coverage is expected).

**Done when:** given two 5-hero lineups with known roles, returns a matchup score in the right ballpark (typically −5 to +5 for reasonably balanced drafts).

---

### Step 5 — Tier D: global meta + full prediction  `[x]`
**File:** `app/probability.py`

Add `_meta_score(slots: list[PlayerSlot]) -> float`:
- For each slot: `meta_delta[hero_id][role]` from global stats
- Returns sum over 5 players

Add `predict(radiant: list[PlayerSlot], dire: list[PlayerSlot]) -> PredictionResult`:
- Calls `_score_player` × 10
- Calls `_synergy_score` × 2 teams
- Calls `_matchup_score` once
- Calls `_meta_score` × 2 teams
- Assembles `TeamPrediction` for each side
- Computes `win_probability_radiant = sigmoid((r_score − d_score) / T)`
- Computes `confidence` rating
- Derives `top_factors` list (top 3 signals by absolute contribution)

Add `load_weights(path)` / `save_weights(path)` for `data/model_weights.json`.

**Done when:** `model.predict(radiant_slots, dire_slots)` returns a full `PredictionResult` dict with all fields populated.

---

### Step 6 — Pydantic models + FastAPI route  `[x]`
**Files:** `app/models.py`, `app/routes/probability.py`, `app/main.py`

In `app/models.py` add:
- `PlayerSlotRequest` — `account_id: int | None`, `hero_id: int`, `role: int`, `is_radiant: bool`
- `DraftRequest` — `players: list[PlayerSlotRequest]` (exactly 10, validated)
- `PlayerPredictionResponse`, `TeamPredictionResponse`, `PredictionResponse`

In `app/routes/probability.py`:
- `POST /probability/predict` — validates request, calls `model.predict()`, returns `PredictionResponse`
- `GET /probability/calibrate` — triggers weight recalibration from DEEP cache, saves `model_weights.json`, returns summary

In `app/main.py`: register the new router.

Model instance lives as a module-level singleton, loaded once at startup via FastAPI `lifespan`.

**Done when:** `curl -X POST /probability/predict -d '{...}'` returns a valid JSON prediction.

---

### Step 7 — Notebook §14: weight calibration  `[x]`
**Notebook cell:** new §14 section

Steps inside the cell:
1. For each match in DEEP where ≥1 tracked player appears: compute full feature vector (all tier signals for the tracked players, zeros for untracked)
2. Build `X` (feature matrix, one row per match) and `y` (radiant_win labels)
3. Chronological 80/20 train/test split
4. Fit weights via `scipy.optimize.minimize` (negative log-likelihood + L2 penalty on deviation from defaults)
5. Calibrate temperature `T` separately by minimizing Brier score on validation set
6. Plot calibration curve: bucket predictions into deciles, compare predicted vs actual WR
7. Save `data/model_weights.json`
8. Print: validation log-loss, Brier score, accuracy vs naive baseline (always predict 50%)

**Done when:** `data/model_weights.json` exists, validation Brier score < 0.25 (beats naive baseline of 0.25).

---

### Step 8 — Dashboard draft input panel  `[x]`
**File:** `static/dashboard.html`

New section below existing Tier 2 content:
- Header: "Win Probability — Draft Predictor"
- Two columns: Radiant (green) / Dire (red)
- Each column: 5 rows, each row = `[Friend dropdown | Hero picker (autocomplete) | Role selector]`
- Friend dropdown: populated from `friends.json` labels + "Random/Unknown" option
- Hero picker: text input with autocomplete from hero reference list (`/heroes/reference`)
- Role selector: Carry / Mid / Offlane / Support / Jungle
- "Predict" button → `POST /probability/predict`

**Done when:** UI renders correctly, all inputs are selectable, button is wired up to the API.

---

### Step 9 — Dashboard probability display + breakdown  `[ ]`
**File:** `static/dashboard.html`

On prediction response:
- Large win-% bar: gradient green→red with a marker at predicted probability
- Radiant score vs Dire score (numeric)
- Confidence badge (high/medium/low)
- Top 3 factors list (from `top_factors` array)
- Expandable "Full breakdown" accordion:
  - Per-player table: Name | Hero | Role | Baseline WR | Hero Δ | Role Δ | Hero×Role Δ | Form Δ | Total
  - Synergy bonus row per team
  - Matchup score row
  - Meta score row
- Live update: re-predict on each input change (debounced 300ms), not just on button click

**Done when:** full prediction with breakdown renders correctly end-to-end from UI → API → display.

---

### Step 10 — Stratz API: patch-aware meta (optional)  `[→]`
**Files:** `app/collector.py`, `app/probability.py`

Replace or augment `data/hero_global_stats.json` (OpenDota `/heroStats`) with Stratz data,
which adds two things OpenDota lacks:
- **Patch-specific win rates** — `/heroStats` is a rolling aggregate; Stratz lets you filter by patch version
- **Rank-bracket win rates** — heroes perform differently at Herald vs Divine; filter to your group's bracket

**Integration plan:**
- Add `_fetch_stratz_hero_meta(patch, bracket)` to `app/collector.py`
  - Endpoint: `https://api.stratz.com/api/v1/Hero/stats` (REST) or GraphQL at `https://api.stratz.com/graphql`
  - Free API key from stratz.com/api — pass as `Authorization: Bearer <token>`
  - Returns per-hero, per-position pick/win counts filterable by patch + bracket
- Save output to `data/hero_global_stats_stratz.json`
- In `_load_global_meta()`: prefer Stratz file over OpenDota file when both exist
- Add `STRATZ_API_KEY` to `.env` / `app/config.py`

**Note on Dotabuff:** no public API exists; scraping violates their ToS. Stratz is the right choice.

**Note on OpenDota `/explorer`:** the SQL explorer endpoint (`/explorer?sql=...`) can also query
patch-specific aggregates from their match DB — a zero-dependency alternative if Stratz key is unavailable.

---

## Calibration Notes

- Default temperature `T = 12.0` means a +12% team score advantage → ~73% win probability
- Weight calibration requires `data/diff_player_x_*.parquet` AND a full DEEP cache (~800 matches)
- If parquet files don't exist (§13 not run), `WinProbabilityModel.load()` still works but all deltas = 0 (pure baseline + matchup model)
- Weights are re-calibratable at any time via `GET /probability/calibrate`

## Stratz Integration Notes

- `app/stratz.py` — StratzClient + normalisation helpers
- API key required: add `STRATZ_API_KEY=your_token` to `.env`
- Default brackets: Legend (5) + Ancient (6) — change via `stratz_brackets` in `.env`
- `python cli.py refresh-data` now fetches Stratz meta automatically when key is set
- Merged file `hero_global_stats_merged.json` is preferred by `_load_global_meta()`; falls back through Stratz-only, then OpenDota global
- Stratz rate limit: ~1 req/sec free tier — 5 calls for position stats (~6 sec total)
- Matchup enrichment from Stratz (bracket-specific) is not yet implemented; tracked in Step 10

## Known Constraints

- Hero matchup coverage in `hero_matchups.json` is limited to top 10 heroes per player (~40–50 unique heroes). Matchup edges for heroes outside this set will be missing — handled by skipping those pairs.
- `player_role_stats.json` gives A4 data but is fetched via the API (last 100 matches, not 200). DEEP cache is richer — if both are available, DEEP takes precedence for A4.
- Training data (~700 matches) is limited. L2 regularization is essential; weights should not deviate far from defaults.
- `lane_role` is missing for a fraction of DEEP matches (OpenDota doesn't always parse it). Those matches contribute to A1/A2/A5 but not A3/A4.
