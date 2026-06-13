from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from condocharge.api.deps import CurrentUser, DbSession
from condocharge.api.v1._helpers import build_resident_session_response, paginate, session_detail_query
from condocharge.api.v1.stations import _resolve_legrand_credentials, _stations_live_occupancy
from condocharge.models.charging import ChargingSession, ChargingStation, RfidUser
from condocharge.models.tenancy import ResidentNotificationPreferences
from condocharge.models.tenancy import Condominium
from condocharge.schemas.api import (
    ResidentSessionListResponse,
    ResidentStationLastCharge,
    ResidentStationOccupancyListResponse,
    ResidentStationOccupancyResponse,
    ResidentStationStatusListResponse,
    ResidentStationStatusResponse,
)
from condocharge.schemas.consumption import (
    MonthlyConsumptionPoint,
    ResidentCardResponse,
    ResidentNotificationPreferencesResponse,
    ResidentNotificationPreferencesUpdateRequest,
    ResidentProfileResponse,
    ResidentSummaryResponse,
    UpdateResidentProfileRequest,
)


router = APIRouter(prefix="/resident", tags=["resident"])


def _require_resident(user: CurrentUser) -> None:
    if user.role != "resident":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@router.get(
    "/summary",
    response_model=ResidentSummaryResponse,
    summary="Get resident consumption summary",
)
def resident_summary(
    db: DbSession,
    current_user: CurrentUser,
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
) -> ResidentSummaryResponse:
    _require_resident(current_user)

    condo = db.get(Condominium, current_user.condominium_id)
    if condo is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")

    cards = db.scalars(
        select(RfidUser)
        .where(RfidUser.condominium_id == current_user.condominium_id)
        .where(RfidUser.app_user_id == current_user.id)
        .order_by(RfidUser.id.asc())
    ).all()
    card_ids = [c.id for c in cards]

    session_filter = [ChargingSession.condominium_id == current_user.condominium_id]
    if from_date is not None:
        session_filter.append(ChargingSession.start_time >= from_date)
    if to_date is not None:
        session_filter.append(ChargingSession.end_time <= to_date)
    if card_ids:
        session_filter.append(ChargingSession.rfid_user_id.in_(card_ids))
    else:
        return ResidentSummaryResponse(
            from_date=from_date,
            to_date=to_date,
            total_sessions=0,
            total_energy_wh=0,
            total_energy_kwh=0.0,
            energy_price_eur_per_kwh=float(condo.energy_price_eur_per_kwh),
            estimated_cost_eur=0.0,
            estimated_annual_cost_eur=0.0,
            latest_session=None,
            cards=[ResidentCardResponse(id=c.id, rfid_id=c.rfid_id, name=c.name) for c in cards],
            monthly_breakdown=[],
        )

    total_sessions = int(db.scalar(select(func.count()).select_from(ChargingSession).where(*session_filter)) or 0)
    total_energy_wh = int(
        db.scalar(select(func.coalesce(func.sum(ChargingSession.energy_wh), 0)).where(*session_filter)) or 0
    )
    latest_session = db.scalar(
        session_detail_query()
        .where(*session_filter)
        .order_by(ChargingSession.end_time.desc(), ChargingSession.id.desc())
        .limit(1)
    )
    monthly_rows = db.execute(
        select(ChargingSession.end_time, ChargingSession.energy_wh)
        .where(*session_filter)
        .order_by(ChargingSession.end_time.asc())
    ).all()

    price = float(condo.energy_price_eur_per_kwh)
    energy_kwh = total_energy_wh / 1000.0
    estimated_cost = round(energy_kwh * price, 2)
    monthly_totals: dict[str, int] = defaultdict(int)
    for end_time, energy_wh in monthly_rows:
        month_key = end_time.strftime("%Y-%m")
        monthly_totals[month_key] += int(energy_wh)

    monthly_breakdown = [
        MonthlyConsumptionPoint(
            month=month_key,
            total_energy_wh=energy_wh,
            total_energy_kwh=round(energy_wh / 1000.0, 3),
            estimated_cost_eur=round((energy_wh / 1000.0) * price, 2),
        )
        for month_key, energy_wh in monthly_totals.items()
    ]
    if from_date is not None and to_date is not None and to_date >= from_date:
        days_span = max(1.0, (to_date - from_date).total_seconds() / 86400.0)
        estimated_annual_cost = round(estimated_cost * (365.0 / days_span), 2)
    else:
        estimated_annual_cost = estimated_cost

    return ResidentSummaryResponse(
        from_date=from_date,
        to_date=to_date,
        total_sessions=total_sessions,
        total_energy_wh=total_energy_wh,
        total_energy_kwh=round(energy_kwh, 3),
        energy_price_eur_per_kwh=price,
        estimated_cost_eur=estimated_cost,
        estimated_annual_cost_eur=estimated_annual_cost,
        latest_session=build_resident_session_response(latest_session) if latest_session is not None else None,
        cards=[ResidentCardResponse(id=c.id, rfid_id=c.rfid_id, name=c.name) for c in cards],
        monthly_breakdown=monthly_breakdown,
    )


@router.get(
    "/sessions",
    response_model=ResidentSessionListResponse,
    summary="List resident charging sessions",
)
def resident_sessions(
    db: DbSession,
    current_user: CurrentUser,
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ResidentSessionListResponse:
    _require_resident(current_user)

    base = session_detail_query()
    count_base = select(ChargingSession.id)

    base = base.where(ChargingSession.condominium_id == current_user.condominium_id)
    count_base = count_base.where(ChargingSession.condominium_id == current_user.condominium_id)

    base = base.join(ChargingSession.rfid_user).where(RfidUser.app_user_id == current_user.id)
    count_base = count_base.join(ChargingSession.rfid_user).where(RfidUser.app_user_id == current_user.id)

    if from_date is not None:
        base = base.where(ChargingSession.start_time >= from_date)
        count_base = count_base.where(ChargingSession.start_time >= from_date)
    if to_date is not None:
        base = base.where(ChargingSession.end_time <= to_date)
        count_base = count_base.where(ChargingSession.end_time <= to_date)

    base = base.order_by(ChargingSession.start_time.desc(), ChargingSession.id.desc())
    sessions, pagination = paginate(db, base_count_from=count_base, query=base, limit=limit, offset=offset)
    return ResidentSessionListResponse(items=[build_resident_session_response(item) for item in sessions], pagination=pagination)


@router.get(
    "/rfid-users",
    response_model=list[ResidentCardResponse],
    summary="List resident RFID cards",
)
def resident_rfid_users(db: DbSession, current_user: CurrentUser) -> list[ResidentCardResponse]:
    _require_resident(current_user)
    rows = db.scalars(
        select(RfidUser)
        .where(RfidUser.condominium_id == current_user.condominium_id)
        .where(RfidUser.app_user_id == current_user.id)
        .order_by(RfidUser.id.asc())
    ).all()
    return [ResidentCardResponse(id=r.id, rfid_id=r.rfid_id, name=r.name) for r in rows]


@router.get(
    "/stations",
    response_model=ResidentStationStatusListResponse,
    summary="List condominium stations (resident-safe)",
)
def resident_stations(db: DbSession, current_user: CurrentUser) -> ResidentStationStatusListResponse:
    _require_resident(current_user)

    stations = db.scalars(
        select(ChargingStation)
        .where(ChargingStation.condominium_id == current_user.condominium_id)
        .order_by(ChargingStation.id.asc())
    ).all()

    items: list[ResidentStationStatusResponse] = []
    for station in stations:
        last_session = db.scalar(
            select(ChargingSession)
            .where(ChargingSession.condominium_id == current_user.condominium_id)
            .where(ChargingSession.station_id == station.id)
            .order_by(ChargingSession.end_time.desc(), ChargingSession.id.desc())
            .limit(1)
        )
        items.append(
            ResidentStationStatusResponse(
                id=station.id,
                name=station.name,
                known_status=station.status,
                last_sync_at=station.last_sync_at,
                last_charge=(
                    ResidentStationLastCharge(
                        end_time=last_session.end_time,
                        energy_wh=int(last_session.energy_wh),
                        total_minutes=int(last_session.total_minutes),
                    )
                    if last_session is not None
                    else None
                ),
            )
        )

    return ResidentStationStatusListResponse(items=items)


@router.get(
    "/stations/occupancy",
    response_model=ResidentStationOccupancyListResponse,
    summary="Get live station occupancy (resident-safe)",
)
def resident_station_occupancy(
    db: DbSession,
    current_user: CurrentUser,
) -> ResidentStationOccupancyListResponse:
    _require_resident(current_user)
    credentials = _resolve_legrand_credentials()
    stations = db.scalars(
        select(ChargingStation)
        .where(ChargingStation.condominium_id == current_user.condominium_id)
        .order_by(ChargingStation.id.asc())
    ).all()
    items = _stations_live_occupancy(stations=stations, credentials=credentials)
    return ResidentStationOccupancyListResponse(
        items=[
            ResidentStationOccupancyResponse(
                station_id=i.station_id,
                computed_status=i.computed_status,
                last_checked_at=i.last_checked_at,
            )
            for i in items
        ]
    )


def _get_or_create_preferences(db: DbSession, *, current_user: CurrentUser) -> ResidentNotificationPreferences:
    prefs = db.scalar(select(ResidentNotificationPreferences).where(ResidentNotificationPreferences.app_user_id == current_user.id))
    if prefs is not None:
        return prefs
    prefs = ResidentNotificationPreferences(
        condominium_id=current_user.condominium_id,
        app_user_id=current_user.id,
        charging_completed=1,
        station_available=1,
        station_back_online=0,
    )
    db.add(prefs)
    db.commit()
    db.refresh(prefs)
    return prefs


@router.get(
    "/notifications/preferences",
    response_model=ResidentNotificationPreferencesResponse,
    summary="Get resident notification preferences",
)
def get_notification_preferences(db: DbSession, current_user: CurrentUser) -> ResidentNotificationPreferencesResponse:
    _require_resident(current_user)
    prefs = _get_or_create_preferences(db, current_user=current_user)
    return ResidentNotificationPreferencesResponse(
        charging_completed=bool(prefs.charging_completed),
        station_available=bool(prefs.station_available),
        station_back_online=bool(prefs.station_back_online),
    )


@router.put(
    "/notifications/preferences",
    response_model=ResidentNotificationPreferencesResponse,
    summary="Update resident notification preferences",
)
def update_notification_preferences(
    db: DbSession,
    current_user: CurrentUser,
    body: ResidentNotificationPreferencesUpdateRequest,
) -> ResidentNotificationPreferencesResponse:
    _require_resident(current_user)
    prefs = _get_or_create_preferences(db, current_user=current_user)
    prefs.charging_completed = 1 if body.charging_completed else 0
    prefs.station_available = 1 if body.station_available else 0
    prefs.station_back_online = 1 if body.station_back_online else 0
    db.commit()
    db.refresh(prefs)
    return ResidentNotificationPreferencesResponse(
        charging_completed=bool(prefs.charging_completed),
        station_available=bool(prefs.station_available),
        station_back_online=bool(prefs.station_back_online),
    )


@router.get(
    "/profile",
    response_model=ResidentProfileResponse,
    summary="Get resident profile",
)
def get_profile(db: DbSession, current_user: CurrentUser) -> ResidentProfileResponse:
    _require_resident(current_user)
    cards = resident_rfid_users(db, current_user)
    prefs = _get_or_create_preferences(db, current_user=current_user)
    return ResidentProfileResponse(
        username=current_user.username,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        apartment_or_unit=current_user.apartment_or_unit,
        email=current_user.email,
        phone_number=current_user.phone_number,
        linked_cards=cards,
        notification_preferences=ResidentNotificationPreferencesResponse(
            charging_completed=bool(prefs.charging_completed),
            station_available=bool(prefs.station_available),
            station_back_online=bool(prefs.station_back_online),
        ),
    )


@router.patch(
    "/profile",
    response_model=ResidentProfileResponse,
    summary="Update resident profile contact details",
)
def update_profile(db: DbSession, current_user: CurrentUser, body: UpdateResidentProfileRequest) -> ResidentProfileResponse:
    _require_resident(current_user)
    if "email" in body.model_fields_set:
        current_user.email = body.email
    if "phone_number" in body.model_fields_set:
        current_user.phone_number = body.phone_number
    db.commit()
    db.refresh(current_user)
    return get_profile(db, current_user)
