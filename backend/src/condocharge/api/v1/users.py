from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status
from sqlalchemy import select

from condocharge.api.deps import DbSession, NonResidentUser
from condocharge.api.v1._helpers import (
    build_session_response,
    paginate,
    user_latest_session,
    user_totals,
)
from condocharge.models.charging import RfidUser
from condocharge.schemas.api import UserListResponse, UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "",
    response_model=UserListResponse,
    summary="List RFID users",
    description="Returns imported RFID users with pagination and aggregate session/energy counters.",
)
def list_users(
    db: DbSession,
    current_user: NonResidentUser,
    limit: Annotated[int, Query(ge=1, le=200, description="Maximum number of users to return")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of users to skip")] = 0,
) -> UserListResponse:
    base = (
        select(RfidUser)
        .where(RfidUser.condominium_id == current_user.condominium_id)
        .order_by(RfidUser.id.asc())
    )
    users, pagination = paginate(
        db,
        base_count_from=select(RfidUser.id).where(RfidUser.condominium_id == current_user.condominium_id),
        query=base,
        limit=limit,
        offset=offset,
    )

    items = []
    for user in users:
        session_count, total_energy_wh = user_totals(db, user_id=user.id)
        latest_session = user_latest_session(db, user_id=user.id)
        items.append(
            UserResponse(
                id=user.id,
                rfid_id=user.rfid_id,
                name=user.name,
                created_at=user.created_at,
                updated_at=user.updated_at,
                session_count=session_count,
                total_energy_wh=total_energy_wh,
                latest_session=build_session_response(latest_session) if latest_session is not None else None,
            )
        )
    return UserListResponse(items=items, pagination=pagination)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get RFID user details",
    description="Returns a single RFID user with aggregate counters and latest charging session.",
)
def get_user(
    db: DbSession,
    current_user: NonResidentUser,
    user_id: int = Path(..., ge=1, description="RFID user database identifier"),
) -> UserResponse:
    user = db.get(RfidUser, user_id)
    if user is None or user.condominium_id != current_user.condominium_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    session_count, total_energy_wh = user_totals(db, user_id=user.id)
    latest_session = user_latest_session(db, user_id=user.id)
    return UserResponse(
        id=user.id,
        rfid_id=user.rfid_id,
        name=user.name,
        created_at=user.created_at,
        updated_at=user.updated_at,
        session_count=session_count,
        total_energy_wh=total_energy_wh,
        latest_session=build_session_response(latest_session) if latest_session is not None else None,
    )
