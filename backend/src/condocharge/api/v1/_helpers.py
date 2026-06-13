from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from condocharge.models.charging import ChargingSession
from condocharge.schemas.api import (
    PaginationMeta,
    ResidentSessionResponse,
    ResidentStationRef,
    RfidUserRef,
    SessionResponse,
    StationRef,
)


def paginate[T](
    db: Session,
    *,
    base_count_from: Select[Any],
    query: Select[tuple[T]],
    limit: int,
    offset: int,
) -> tuple[Sequence[T], PaginationMeta]:
    total = db.scalar(select(func.count()).select_from(base_count_from.subquery())) or 0
    items = db.scalars(query.limit(limit).offset(offset)).all()
    return items, PaginationMeta(total=total, limit=limit, offset=offset)


def build_session_response(row: ChargingSession) -> SessionResponse:
    station = (
        StationRef(id=row.station.id, host=row.station.host, vendor=row.station.vendor, name=row.station.name)
        if row.station is not None
        else None
    )
    rfid_user = (
        RfidUserRef(id=row.rfid_user.id, rfid_id=row.rfid_user.rfid_id, name=row.rfid_user.name)
        if row.rfid_user is not None
        else None
    )
    return SessionResponse(
        id=row.id,
        source_key=row.source_key,
        station_id=row.station_id,
        rfid_user_id=row.rfid_user_id,
        start_time=row.start_time,
        end_time=row.end_time,
        energy_wh=row.energy_wh,
        total_minutes=row.total_minutes,
        charging_minutes=row.charging_minutes,
        idle_minutes=row.idle_minutes,
        plug_type=row.plug_type,
        created_at=row.created_at,
        updated_at=row.updated_at,
        station=station,
        rfid_user=rfid_user,
    )


def build_resident_session_response(row: ChargingSession) -> ResidentSessionResponse:
    station = (
        ResidentStationRef(id=row.station.id, name=row.station.name)
        if row.station is not None
        else None
    )
    rfid_user = (
        RfidUserRef(id=row.rfid_user.id, rfid_id=row.rfid_user.rfid_id, name=row.rfid_user.name)
        if row.rfid_user is not None
        else None
    )
    return ResidentSessionResponse(
        id=row.id,
        source_key=row.source_key,
        station_id=row.station_id,
        rfid_user_id=row.rfid_user_id,
        start_time=row.start_time,
        end_time=row.end_time,
        energy_wh=row.energy_wh,
        total_minutes=row.total_minutes,
        charging_minutes=row.charging_minutes,
        idle_minutes=row.idle_minutes,
        plug_type=row.plug_type,
        created_at=row.created_at,
        updated_at=row.updated_at,
        station=station,
        rfid_user=rfid_user,
    )


def session_detail_query() -> Select[tuple[ChargingSession]]:
    return select(ChargingSession).options(
        joinedload(ChargingSession.station),
        joinedload(ChargingSession.rfid_user),
    )


def station_latest_session(db: Session, *, station_id: int) -> ChargingSession | None:
    return db.scalar(
        session_detail_query()
        .where(ChargingSession.station_id == station_id)
        .order_by(ChargingSession.end_time.desc(), ChargingSession.id.desc())
        .limit(1)
    )


def user_latest_session(db: Session, *, user_id: int) -> ChargingSession | None:
    return db.scalar(
        session_detail_query()
        .where(ChargingSession.rfid_user_id == user_id)
        .order_by(ChargingSession.end_time.desc(), ChargingSession.id.desc())
        .limit(1)
    )


def station_totals(db: Session, *, station_id: int) -> tuple[int, int]:
    row = db.execute(
        select(
            func.count(ChargingSession.id),
            func.coalesce(func.sum(ChargingSession.energy_wh), 0),
        ).where(ChargingSession.station_id == station_id)
    ).one()
    return int(row[0]), int(row[1])


def user_totals(db: Session, *, user_id: int) -> tuple[int, int]:
    row = db.execute(
        select(
            func.count(ChargingSession.id),
            func.coalesce(func.sum(ChargingSession.energy_wh), 0),
        ).where(ChargingSession.rfid_user_id == user_id)
    ).one()
    return int(row[0]), int(row[1])
