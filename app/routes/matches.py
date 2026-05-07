"""
/matches endpoints
"""

from fastapi import APIRouter, HTTPException
from app.client import get_client

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("/{match_id}")
async def get_match(match_id: int):
    """
    Full match details: all 10 players, itemisation, ward logs, objectives.
    """
    try:
        return await get_client().get_match(match_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
