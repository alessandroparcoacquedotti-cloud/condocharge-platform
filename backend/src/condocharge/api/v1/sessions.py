from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Path, Query, status
from sqlalchemy import select

from condocharge.api.deps import CurrentUser, DbSession
from condocharge.api.v1._helpers import build_session_response, paginate, session_detail_query
from condocharge.models.charging import ChargingSession, RfidUser
from condocharge.schemas.api import SessionListResponse, SessionResponse


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get(
    "",
    response_model=SessionListResponse,
    summary="List charging sessions",
    description="Returns imported charging sessions with optional filters and pagination.",
)
def list_sessions(
    db: DbSession,
    current_user: CurrentUser,
    from_date: datetime | None = Query(default=None, description="Filter sessions starting on or after this ISO datetime"),
    to_date: datetime | None = Query(default=None, description="Filter sessions ending on or before this ISO datetime"),
    start_date: datetime | None = Query(default=None, description="Filter sessions starting on or after this ISO datetime"),
    end_date: datetime | None = Query(default=None, description="Filter sessions ending on or before this ISO datetime"),
    rfid_id: str | None = Query(default=None, description="Filter by RFID card identifier"),
    station_id: int | None = Query(default=None, ge=1, description="Filter by charging station identifier"),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum number of sessions to return"),
    offset: int = Query(default=0, ge=0, description="Number of sessions to skip"),
) -> SessionListResponse:
    base = session_detail_query()
    count_base = select(ChargingSession.id)

    base = base.where(ChargingSession.condominium_id == current_user.condominium_id)
    count_base = count_base.where(ChargingSession.condominium_id == current_user.condominium_id)

    effective_from = from_date or start_date
    effective_to = to_date or end_date
    if effective_from is not None:
        base = base.where(ChargingSession.start_time >= effective_from)
        count_base = count_base.where(ChargingSession.start_time >= effective_from)
    if effective_to is not None:
        base = base.where(ChargingSession.end_time <= effective_to)
        count_base = count_base.where(ChargingSession.end_time <= effective_to)
    if station_id is not None:
        base = base.where(ChargingSession.station_id == station_id)
        count_base = count_base.where(ChargingSession.station_id == station_id)
    if rfid_id is not None:
        base = base.join(ChargingSession.rfid_user).where(RfidUser.rfid_id == rfid_id)
        count_base = count_base.join(ChargingSession.rfid_user).where(RfidUser.rfid_id == rfid_id)

    if current_user.role == "resident":
        base = base.join(ChargingSession.rfid_user).where(RfidUser.app_user_id == current_user.id)
        count_base = count_base.join(ChargingSession.rfid_user).where(RfidUser.app_user_id == current_user.id)

    base = base.order_by(ChargingSession.start_time.desc(), ChargingSession.id.desc())

    sessions, pagination = paginate(
        db,
        base_count_from=count_base,
        query=base,
        limit=limit,
        offset=offset,
    )
    return SessionListResponse(items=[build_session_response(item) for item in sessions], pagination=pagination)


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Get charging session details",
    description="Returns a single imported charging session, including its station and RFID user references.",
)
def get_session(
    db: DbSession,
    current_user: CurrentUser,
    session_id: int = Path(..., ge=1, description="Charging session database identifier"),
) -> SessionResponse:
    row = db.scalar(
        session_detail_query()
        .where(ChargingSession.id == session_id)
        .where(ChargingSession.condominium_id == current_user.condominium_id)
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if current_user.role == "resident":
        if row.rfid_user is None or row.rfid_user.app_user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return build_session_response(row)
