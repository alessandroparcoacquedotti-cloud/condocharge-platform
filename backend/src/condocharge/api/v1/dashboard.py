from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from condocharge.api.deps import DbSession, NonResidentUser
from condocharge.api.v1._helpers import build_session_response, session_detail_query
from condocharge.models.charging import AgentState, ChargingSession, ChargingStation, RfidUser
from condocharge.schemas.api import (
    AgentStatusResponse,
    DashboardSummaryResponse,
    TopUserByEnergyResponse,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
_logger = logging.getLogger("uvicorn.error")


def _build_agent_status(*, db: DbSession, condominium_id: int, now: datetime | None = None) -> AgentStatusResponse:
    now = now or datetime.now(tz=UTC)
    state = db.scalar(
        select(AgentState)
        .where(AgentState.condominium_id == condominium_id)
        .order_by(AgentState.updated_at.desc(), AgentState.id.desc())
        .limit(1)
    )
    if state is None or state.last_heartbeat_at is None:
        return AgentStatusResponse(
            agent_id=state.agent_id if state is not None else None,
            online=False,
            health_color="red",
            last_heartbeat=state.last_heartbeat_at if state is not None else None,
            last_station_update=state.last_station_update_at if state is not None else None,
            last_session_import=state.last_session_import_at if state is not None else None,
            heartbeat_count=int(state.heartbeat_count) if state is not None else 0,
            polling_count=int(state.polling_count) if state is not None else 0,
            import_count=int(state.import_count) if state is not None else 0,
            retry_count=int(state.retry_count) if state is not None else 0,
            failure_count=int(state.failure_count) if state is not None else 0,
        )

    heartbeat_age = (now - state.last_heartbeat_at.astimezone(UTC)).total_seconds()
    if heartbeat_age < 90:
        health_color = "green"
        online = True
    elif heartbeat_age <= 180:
        health_color = "yellow"
        online = True
    else:
        health_color = "red"
        online = False

    return AgentStatusResponse(
        agent_id=state.agent_id,
        online=online,
        health_color=health_color,
        last_heartbeat=state.last_heartbeat_at,
        last_station_update=state.last_station_update_at,
        last_session_import=state.last_session_import_at,
        heartbeat_count=int(state.heartbeat_count),
        polling_count=int(state.polling_count),
        import_count=int(state.import_count),
        retry_count=int(state.retry_count),
        failure_count=int(state.failure_count),
    )


@router.get(
    "/agent-status",
    response_model=AgentStatusResponse,
    summary="Get latest agent status for the current condominium",
)
def get_agent_status(
    db: DbSession,
    current_user: NonResidentUser,
) -> AgentStatusResponse:
    return _build_agent_status(db=db, condominium_id=current_user.condominium_id)


@router.get(
    "/summary",
    response_model=DashboardSummaryResponse,
    summary="Get dashboard summary",
    description="Returns headline charging metrics, the latest session, and top RFID users ranked by imported energy.",
)
def get_dashboard_summary(
    db: DbSession,
    current_user: NonResidentUser,
    response: Response,
    from_date: Annotated[datetime | None, Query(description="Filter sessions starting on or after this ISO datetime")] = None,
    to_date: Annotated[datetime | None, Query(description="Filter sessions ending on or before this ISO datetime")] = None,
) -> DashboardSummaryResponse:
    t0 = time.perf_counter()
    condo_id = current_user.condominium_id
    session_filter = []
    if from_date is not None:
        session_filter.append(ChargingSession.start_time >= from_date)
    if to_date is not None:
        session_filter.append(ChargingSession.end_time <= to_date)

    t_sql0 = time.perf_counter()
    sessions_agg_row = db.execute(
        select(
            func.count(ChargingSession.id),
            func.coalesce(func.sum(ChargingSession.energy_wh), 0),
        )
        .where(ChargingSession.condominium_id == condo_id)
        .where(*session_filter)
    ).one()
    total_sessions = int(sessions_agg_row[0] or 0)
    total_energy_wh = int(sessions_agg_row[1] or 0)
    total_sessions_energy_ms = (time.perf_counter() - t_sql0) * 1000.0

    t_sql1 = time.perf_counter()
    total_users = int(db.scalar(select(func.count()).select_from(RfidUser).where(RfidUser.condominium_id == condo_id)) or 0)
    total_users_ms = (time.perf_counter() - t_sql1) * 1000.0

    t_sql2 = time.perf_counter()
    total_stations = int(
        db.scalar(select(func.count()).select_from(ChargingStation).where(ChargingStation.condominium_id == condo_id)) or 0
    )
    total_stations_ms = (time.perf_counter() - t_sql2) * 1000.0

    t_sql3 = time.perf_counter()
    latest_session = db.scalar(
        session_detail_query()
        .where(ChargingSession.condominium_id == condo_id)
        .where(*session_filter)
        .order_by(ChargingSession.end_time.desc(), ChargingSession.id.desc())
        .limit(1)
    )
    latest_session_ms = (time.perf_counter() - t_sql3) * 1000.0

    t_sql4 = time.perf_counter()
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
    top_users_ms = (time.perf_counter() - t_sql4) * 1000.0

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

    t_sql5 = time.perf_counter()
    agent_status = _build_agent_status(db=db, condominium_id=condo_id)
    agent_status_ms = (time.perf_counter() - t_sql5) * 1000.0

    model = DashboardSummaryResponse(
        total_sessions=total_sessions,
        total_energy_wh=total_energy_wh,
        total_energy_kwh=round(total_energy_wh / 1000.0, 3),
        total_users=total_users,
        total_stations=total_stations,
        latest_session=build_session_response(latest_session) if latest_session is not None else None,
        top_users_by_energy=top_users,
        agent_status=agent_status,
    )

    t_ser0 = time.perf_counter()
    payload_json = model.model_dump_json()
    payload_bytes = len(payload_json.encode("utf-8"))
    serialize_ms = (time.perf_counter() - t_ser0) * 1000.0

    sql_ms = (
        total_sessions_energy_ms
        + total_users_ms
        + total_stations_ms
        + latest_session_ms
        + top_users_ms
        + agent_status_ms
    )
    total_ms = (time.perf_counter() - t0) * 1000.0
    query_count = 6

    response.headers["X-CondoCharge-Perf-Total-Ms"] = f"{total_ms:.2f}"
    response.headers["X-CondoCharge-Perf-SQL-Ms"] = f"{sql_ms:.2f}"
    response.headers["X-CondoCharge-Perf-Serialize-Ms"] = f"{serialize_ms:.2f}"
    response.headers["X-CondoCharge-Perf-Payload-Bytes"] = str(payload_bytes)
    response.headers["X-CondoCharge-Perf-Query-Count"] = str(query_count)

    _logger.info(
        "dashboard_summary_perf condo_id=%s total_ms=%.2f sql_ms=%.2f serialize_ms=%.2f payload_bytes=%s query_count=%s breakdown_ms=%s",
        condo_id,
        total_ms,
        sql_ms,
        serialize_ms,
        payload_bytes,
        query_count,
        {
            "sessions_agg": round(total_sessions_energy_ms, 2),
            "total_users": round(total_users_ms, 2),
            "total_stations": round(total_stations_ms, 2),
            "latest_session": round(latest_session_ms, 2),
            "top_users": round(top_users_ms, 2),
            "agent_status": round(agent_status_ms, 2),
        },
    )

    return model
