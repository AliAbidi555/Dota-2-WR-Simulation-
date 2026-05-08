"""
/probability — win probability predictions for a given 10-player draft.

Endpoints:
  POST /probability/predict   — full prediction for a draft
  POST /probability/reload    — reload model from disk (after refresh-data)
"""

from fastapi import APIRouter, HTTPException

from app.models import (
    DraftRequest,
    FactorResponse,
    PlayerPredictionResponse,
    PredictionResponse,
    SynergyEntryResponse,
    TeamPredictionResponse,
)
from app.probability import PlayerSlot, PredictionResult, TeamPrediction, get_model, reset_model

router = APIRouter(prefix="/probability", tags=["probability"])


# -- Conversion helpers --------------------------------------------------------

def _player_response(p) -> PlayerPredictionResponse:
    return PlayerPredictionResponse(
        label                = p.label,
        hero_id              = p.hero_id,
        role                 = p.role,
        baseline_wr          = p.baseline_wr,
        fit_path             = p.fit_path,
        player_score         = p.player_score,
        hero_delta_adj       = p.hero_delta_adj,
        role_delta_adj       = p.role_delta_adj,
        hero_role_delta_adj  = p.hero_role_delta_adj,
        form_delta           = p.form_delta,
    )


def _team_response(t: TeamPrediction) -> TeamPredictionResponse:
    return TeamPredictionResponse(
        players         = [_player_response(p) for p in t.players],
        synergy_entries = [
            SynergyEntryResponse(
                player_a  = e.player_a,
                player_b  = e.player_b,
                raw_delta = e.raw_delta,
                n         = e.n,
                adjusted  = e.adjusted,
            )
            for e in t.synergy.entries
        ],
        synergy_total   = t.synergy.total,
        meta_score      = t.meta_score,
        team_score      = t.team_score,
    )


def _to_response(result: PredictionResult) -> PredictionResponse:
    return PredictionResponse(
        radiant                  = _team_response(result.radiant),
        dire                     = _team_response(result.dire),
        matchup_total            = result.matchup.total,
        matchup_coverage         = result.matchup.coverage,
        radiant_score            = result.radiant_score,
        dire_score               = result.dire_score,
        score_diff               = result.score_diff,
        win_probability_radiant  = result.win_probability_radiant,
        confidence               = result.confidence,
        top_factors              = [
            FactorResponse(label=f.label, signal=f.signal, value=f.value)
            for f in result.top_factors
        ],
    )


# -- Routes --------------------------------------------------------------------

@router.post("/predict", response_model=PredictionResponse)
async def predict_draft(request: DraftRequest) -> PredictionResponse:
    """
    Predict win probability for a 10-player draft.

    Send exactly 10 players: 5 with `is_radiant=true`, 5 with `is_radiant=false`.
    Use `account_id=null` for untracked opponents — they contribute only the
    global 50% baseline and meta signal.
    """
    model = get_model()

    radiant = [
        PlayerSlot(account_id=p.account_id, hero_id=p.hero_id, role=p.role, is_radiant=True)
        for p in request.players if p.is_radiant
    ]
    dire = [
        PlayerSlot(account_id=p.account_id, hero_id=p.hero_id, role=p.role, is_radiant=False)
        for p in request.players if not p.is_radiant
    ]

    result = model.predict(radiant, dire)
    return _to_response(result)


@router.post("/reload", status_code=200)
async def reload_model() -> dict:
    """
    Reload the probability model from disk.

    Call this after running `python cli.py refresh-data` to pick up
    updated parquet files and hero stats without restarting the server.
    """
    model = reset_model()
    s = model.summary
    tick = {True: "ok", False: "--"}
    return {
        "message": "Model reloaded",
        "signals": {
            "baselines":   tick[s.baselines],
            "hero_delta":  tick[s.hero_deltas],
            "role_delta":  tick[s.role_deltas],
            "hero_x_role": tick[s.hero_role],
            "teammate":    tick[s.teammate],
            "matchup":     tick[s.matchup],
            "meta":        tick[s.meta],
            "form":        tick[s.form],
            "weights":     tick[s.weights],
        },
    }
