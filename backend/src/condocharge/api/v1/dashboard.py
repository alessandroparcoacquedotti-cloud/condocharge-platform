from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from condocharge.api.deps import DbSession, NonResidentUser
from condocharge.api.v1._helpers import build_session_response, session_detail_query
from condocharge.models.charging import ChargingSession, ChargingStation, RfidUser
from condocharge.schemas.api import DashboardSummaryResponse, TopUserByEnergyResponse


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get(
    "/summary",
    response_model=DashboardSummaryResponse,
    summary="Get dashboard summary",
    description="Returns headline charging metrics, the latest session, and top RFID users ranked by imported energy.",
)
def get_dashboard_summary(
    db: DbSession,
    current_user: NonResidentUser,
    from_date: datetime | None = Query(default=None, description="Filter sessions starting on or after this ISO datetime"),
    to_date: datetime | None = Query(default=None, description="Filter sessions ending on or before this ISO datetime"),
) -> DashboardSummaryResponse:
    condo_id = current_user.condominium_id
    session_filter = []
    if from_date is not None:
        session_filter.append(ChargingSession.start_time >= from_date)
    if to_date is not None:
        session_filter.append(ChargingSession.end_time <= to_date)

    total_sessions = int(
        db.scalar(
            select(func.count())
            .select_from(ChargingSession)
            .where(ChargingSession.condominium_id == condo_id)
            .where(*session_filter)
        )
        or 0
    )
    total_energy_wh = int(
        db.scalar(
            select(func.coalesce(func.sum(ChargingSession.energy_wh), 0))
            .where(ChargingSession.condominium_id == condo_id)
            .where(*session_filter)
        )
        or 0
    )
    total_users = int(db.scalar(select(func.count()).select_from(RfidUser).where(RfidUser.condominium_id == condo_id)) or 0)
    total_stations = int(
        db.scalar(select(func.count()).select_from(ChargingStation).where(ChargingStation.condominium_id == condo_id)) or 0
    )

    latest_session = db.scalar(
        session_detail_query()
        .where(ChargingSession.condominium_id == condo_id)
        .where(*session_filter)
        .order_by(ChargingSession.end_time.desc(), ChargingSession.id.desc())
        .limit(1)
    )

    top_rows = db.execute(
        select(
            RfidUser.id,
            RfidUser.rfid_id,
            RfidUser.name,
            func.coalesce(func.sum(ChargingSession.energy_wh), 0),
            func.count(ChargingSession.id),
        )
        .join(ChargingSession, ChargingSession.rfid_user_id == RfidUser.id)
        .where(ChargingSession.condominium_id == condo_id)
        .where(RfidUser.condominium_id == condo_id)
        .where(*session_filter)
        .group_by(RfidUser.id, RfidUser.rfid_id, RfidUser.name)
        .order_by(func.sum(ChargingSession.energy_wh).desc(), func.count(ChargingSession.id).desc(), RfidUser.id.asc())
        .limit(5)
    ).all()

    top_users = [
        TopUserByEnergyResponse(
            user_id=int(row[0]),
            rfid_id=str(row[1]),
            name=row[2],
            total_energy_wh=int(row[3]),
            total_energy_kwh=round(int(row[3]) / 1000.0, 3),
            session_count=int(row[4]),
        )
        for row in top_rows
    ]

    return DashboardSummaryResponse(
        total_sessions=total_sessions,
        total_energy_wh=total_energy_wh,
        total_energy_kwh=round(total_energy_wh / 1000.0, 3),
        total_users=total_users,
        total_stations=total_stations,
        latest_session=build_session_response(latest_session) if latest_session is not None else None,
        top_users_by_energy=top_users,
    )
