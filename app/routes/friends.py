"""
/friends endpoints – manage the list of tracked players stored in friends.json
"""

import json
from fastapi import APIRouter, HTTPException
from app.config import settings
from app.models import FriendsConfig, Friend, AddFriendRequest, MessageResponse

router = APIRouter(prefix="/friends", tags=["friends"])


def _load() -> FriendsConfig:
    if not settings.friends_file.exists():
        return FriendsConfig(friends=[])
    with open(settings.friends_file) as f:
        return FriendsConfig(**json.load(f))


def _save(config: FriendsConfig) -> None:
    with open(settings.friends_file, "w") as f:
        json.dump(config.model_dump(), f, indent=2)


@router.get("/", response_model=FriendsConfig)
async def list_friends():
    """Return the current list of tracked friends."""
    return _load()


@router.post("/", response_model=MessageResponse, status_code=201)
async def add_friend(body: AddFriendRequest):
    """Add a Steam account ID to the tracked friends list."""
    config = _load()
    existing_ids = {f.account_id for f in config.friends}
    if body.account_id in existing_ids:
        raise HTTPException(status_code=409, detail="Friend already tracked.")
    config.friends.append(Friend(account_id=body.account_id, label=body.label))
    _save(config)
    return MessageResponse(
        message=f"Added {body.account_id} to friends.",
        data={"account_id": body.account_id, "label": body.label},
    )


@router.delete("/{account_id}", response_model=MessageResponse)
async def remove_friend(account_id: int):
    """Remove a tracked friend by Steam account ID."""
    config = _load()
    before = len(config.friends)
    config.friends = [f for f in config.friends if f.account_id != account_id]
    if len(config.friends) == before:
        raise HTTPException(status_code=404, detail="Friend not found.")
    _save(config)
    return MessageResponse(message=f"Removed {account_id} from friends.")
