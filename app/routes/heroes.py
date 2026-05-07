"""
/heroes — hero reference data
"""

from fastapi import APIRouter, HTTPException
from app.client import get_client

router = APIRouter(prefix="/heroes", tags=["heroes"])


@router.get("/reference")
async def get_heroes_reference():
    """Hero reference list: id → localized_name, primary_attr, roles, attack_type."""
    try:
        return await get_client().get_heroes_reference()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
