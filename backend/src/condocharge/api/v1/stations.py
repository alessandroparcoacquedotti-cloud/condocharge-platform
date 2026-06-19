from __future__ import annotations

import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Path, Query, status
from sqlalchemy import select

from condocharge.api.deps import DbSession, NonResidentUser
from condocharge.api.v1._helpers import (
    build_session_response,
    paginate,
    station_latest_session,
    station_totals,
)
from condocharge.app.integrations.base.models import (
    ConnectorStatus,
)
from condocharge.app.integrations.legrand.driver import LegrandGreenUpDriver
from condocharge.core.config import get_settings
from condocharge.models.charging import ChargingStation
from condocharge.schemas.api import (
    StationListResponse,
    StationOccupancyListResponse,
    StationOccupancyResponse,
    StationResponse,
)

router = APIRouter(prefix="/stations", tags=["stations"])

_live_driver_lock = Lock()
_live_driver = LegrandGreenUpDriver(
    timeout=httpx.Timeout(connect=3.0, read=7.5, write=7.5, pool=7.5),
    max_retries=1,
)
_live_driver_hosts: set[str] = set()

_FREE_OCCUPANCY_STATES = {"available", "free"}
_BUSY_OCCUPANCY_STATES = {"charging", "occupied", "busy"}
_UNAVAILABLE_OCCUPANCY_STATES = {
    "faulted",
    "unknown",
    "unreachable",
    "degraded",
    "offline",
    "unavailable",
}

def _normalize_runtime_state(value: str | ConnectorStatus | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _station_observed_at(station: ChargingStation) -> datetime | None:
    timestamps = [
        _normalize_station_timestamp(getattr(station, "last_seen_at", None)),
        _normalize_station_timestamp(getattr(station, "last_poll_at", None)),
    ]
    values = [value for value in timestamps if value is not None]
    if not values:
        return None
    return max(values)


def _status_is_fresh(*, station: ChargingStation, stale_after_seconds: int) -> bool:
    if _normalize_runtime_state(getattr(station, "status_source", None)) != "agent":
        return False
    observed_at = _station_observed_at(station)
    if observed_at is None:
        return False
    now = datetime.now(tz=UTC)
    return (now - observed_at) <= timedelta(seconds=max(1, stale_after_seconds))


def _map_occupancy_status(
    *,
    connector_status: str | ConnectorStatus | None = None,
    station_status: str | None = None,
    availability: str | None = None,
    reachable: bool = True,
) -> str:
    if not reachable:
        return "unavailable"

    availability_state = _normalize_runtime_state(availability)
    if availability_state in _UNAVAILABLE_OCCUPANCY_STATES:
        return "unavailable"

    connector_state = _normalize_runtime_state(connector_status)
    if connector_state in _FREE_OCCUPANCY_STATES:
        return "free"
    if connector_state in _BUSY_OCCUPANCY_STATES:
        return "busy"
    if connector_state in _UNAVAILABLE_OCCUPANCY_STATES:
        return "unavailable"

    station_state = _normalize_runtime_state(station_status)
    if station_state in _FREE_OCCUPANCY_STATES:
        return "free"
    if station_state in _BUSY_OCCUPANCY_STATES:
        return "busy"
    if station_state in _UNAVAILABLE_OCCUPANCY_STATES:
        return "unavailable"

    return "unavailable"


def _read_windows_generic_credential(target_name: str) -> tuple[str, str] | None:
    if sys.platform != "win32":
        return None

    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", wintypes.LPBYTE),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", wintypes.LPVOID),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    cred_read = advapi32.CredReadW
    cred_read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    cred_read.restype = wintypes.BOOL

    cred_free = advapi32.CredFree
    cred_free.argtypes = [ctypes.c_void_p]
    cred_free.restype = None

    CRED_TYPE_GENERIC = 1
    credential_ptr = ctypes.c_void_p()
    ok = cred_read(target_name, CRED_TYPE_GENERIC, 0, ctypes.byref(credential_ptr))
    if not ok:
        return None

    try:
        cred = ctypes.cast(credential_ptr, ctypes.POINTER(CREDENTIALW)).contents
        username = cred.UserName or ""
        password = ""
        if cred.CredentialBlob and cred.CredentialBlobSize:
            password = ctypes.wstring_at(cred.CredentialBlob, cred.CredentialBlobSize // 2) or ""
        username = username.strip()
        password = password.strip()
        if not username or not password:
            return None
        return username, password
    finally:
        cred_free(credential_ptr)


def _resolve_legrand_credentials() -> tuple[str, str] | None:
    settings = get_settings()
    username = settings.legrand_username.strip()
    password = settings.legrand_password.strip()
    if username and password:
        return username, password
    return _read_windows_generic_credential("CondoCharge-Legrand")


def _station_occupancy_snapshot(
    *,
    station: ChargingStation,
    credentials: tuple[str, str] | None,
) -> StationOccupancyResponse:
    now = datetime.now(tz=UTC)
    if credentials is None:
        return StationOccupancyResponse(
            station_id=station.id,
            host=station.host,
            connector_status=None,
            computed_status="unavailable",
            last_checked_at=now,
            source="live",
        )

    try:
        username, password = credentials
        with _live_driver_lock:
            if station.host not in _live_driver_hosts:
                _live_driver.login(station.host, username, password)
                _live_driver_hosts.add(station.host)
            status = _live_driver.get_station_status(station.host)
        observed_at = datetime.now(tz=UTC)
        connector = status.connector_status or ConnectorStatus.UNKNOWN
        computed = _map_occupancy_status(
            connector_status=connector,
            availability="online",
            reachable=True,
        )

        return StationOccupancyResponse(
            station_id=station.id,
            host=station.host,
            connector_status=str(connector),
            computed_status=computed,
            last_checked_at=observed_at,
            source="live",
        )
    except Exception:
        return StationOccupancyResponse(
            station_id=station.id,
            host=station.host,
            connector_status=None,
            computed_status="unavailable",
            last_checked_at=now,
            source="live",
        )


def _stations_live_occupancy(
    *,
    stations: Sequence[ChargingStation],
    credentials: tuple[str, str] | None,
) -> list[StationOccupancyResponse]:
    if not stations:
        return []
    return [_station_occupancy_snapshot(station=s, credentials=credentials) for s in stations]


def _normalize_station_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _station_occupancy_snapshot_agent(*, station: ChargingStation) -> StationOccupancyResponse:
    observed_at = _station_observed_at(station) or datetime.now(tz=UTC)
    raw_connector = getattr(station, "connector_status", None)
    connector = str(raw_connector) if raw_connector is not None else None
    computed = _map_occupancy_status(
        connector_status=connector,
        station_status=station.status,
        reachable=True,
    )
    return StationOccupancyResponse(
        station_id=station.id,
        host=station.host,
        connector_status=connector,
        computed_status=computed,
        last_checked_at=observed_at,
        source="agent",
    )


def _station_occupancy_snapshot_db(*, station: ChargingStation) -> StationOccupancyResponse:
    settings = get_settings()
    now = datetime.now(tz=UTC)
    observed_at = _station_observed_at(station)
    last_checked_at = observed_at if observed_at is not None else now
    stale_after = max(1, int(settings.agent_stale_after_seconds))
    is_stale = observed_at is None or (now - observed_at) > timedelta(seconds=stale_after)
    if is_stale:
        return StationOccupancyResponse(
            station_id=station.id,
            host=station.host,
            connector_status=None,
            computed_status="unavailable",
            last_checked_at=last_checked_at,
            source="db",
        )
    return _station_occupancy_snapshot_agent(station=station)


def _stations_db_occupancy(*, stations: Sequence[ChargingStation]) -> list[StationOccupancyResponse]:
    return [_station_occupancy_snapshot_db(station=s) for s in stations]


def _station_occupancy_snapshot_with_fallback(
    *,
    station: ChargingStation,
    credentials: tuple[str, str] | None,
    stale_after_seconds: int,
) -> StationOccupancyResponse:
    if _status_is_fresh(station=station, stale_after_seconds=stale_after_seconds):
        return _station_occupancy_snapshot_agent(station=station)
    return _station_occupancy_snapshot(station=station, credentials=credentials)


def _stations_hybrid_occupancy(
    *,
    stations: Sequence[ChargingStation],
    credentials: tuple[str, str] | None,
    stale_after_seconds: int,
) -> list[StationOccupancyResponse]:
    return [
        _station_occupancy_snapshot_with_fallback(
            station=station,
            credentials=credentials,
            stale_after_seconds=stale_after_seconds,
        )
        for station in stations
    ]


@router.get(
    "",
    response_model=StationListResponse,
    summary="List charging stations",
    description="Returns imported charging stations with pagination and aggregate energy/session counters.",
)
def list_stations(
    db: DbSession,
    current_user: NonResidentUser,
    limit: Annotated[int, Query(ge=1, le=200, description="Maximum number of stations to return")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of stations to skip")] = 0,
) -> StationListResponse:
    settings = get_settings()
    stale_after = max(1, int(getattr(settings, "agent_stale_after_seconds", 180) or 180))
    base = (
        select(ChargingStation)
        .where(ChargingStation.condominium_id == current_user.condominium_id)
        .order_by(ChargingStation.id.asc())
    )
    stations, pagination = paginate(
        db,
        base_count_from=select(ChargingStation.id).where(ChargingStation.condominium_id == current_user.condominium_id),
        query=base,
        limit=limit,
        offset=offset,
    )

    items = []
    for station in stations:
        session_count, total_energy_wh = station_totals(db, station_id=station.id)
        latest_session = station_latest_session(db, station_id=station.id)
        items.append(
            StationResponse(
                id=station.id,
                host=station.host,
                vendor=station.vendor,
                name=station.name,
                created_at=station.created_at,
                updated_at=station.updated_at,
                session_count=session_count,
                total_energy_wh=total_energy_wh,
                latest_session=build_session_response(latest_session) if latest_session is not None else None,
                status=station.status,
                status_source=station.status_source,
                last_sync_at=station.last_sync_at,
                last_seen_at=station.last_seen_at,
                last_poll_at=station.last_poll_at,
                connector_status=station.connector_status,
                charging_state=station.charging_state,
                status_is_fresh=_status_is_fresh(station=station, stale_after_seconds=stale_after),
                active_session=False,
                active_session_source="last_sync",
            )
        )
    return StationListResponse(items=items, pagination=pagination)


@router.get(
    "/occupancy",
    response_model=StationOccupancyListResponse,
    summary="Get live station occupancy (free/busy/unavailable)",
    description="Retrieves current connector status via the Legrand integration. Read-only and does not modify the database.",
)
def station_occupancy(
    db: DbSession,
    current_user: NonResidentUser,
) -> StationOccupancyListResponse:
    stations = db.scalars(
        select(ChargingStation)
        .where(ChargingStation.condominium_id == current_user.condominium_id)
        .order_by(ChargingStation.id.asc())
    ).all()
    settings = get_settings()
    if settings.normalized_agent_occupancy_source == "db":
        items = _stations_db_occupancy(stations=stations)
    elif settings.normalized_agent_occupancy_source == "live_only":
        credentials = _resolve_legrand_credentials()
        items = _stations_live_occupancy(stations=stations, credentials=credentials)
    else:
        credentials = _resolve_legrand_credentials()
        items = _stations_hybrid_occupancy(
            stations=stations,
            credentials=credentials,
            stale_after_seconds=max(1, int(getattr(settings, "agent_stale_after_seconds", 180) or 180)),
        )
    return StationOccupancyListResponse(items=items)


@router.get(
    "/{station_id}",
    response_model=StationResponse,
    summary="Get charging station details",
    description="Returns a single station with aggregate counters and its latest imported charging session.",
)
def get_station(
    db: DbSession,
    current_user: NonResidentUser,
    station_id: int = Path(..., ge=1, description="Charging station database identifier"),
) -> StationResponse:
    settings = get_settings()
    stale_after = max(1, int(getattr(settings, "agent_stale_after_seconds", 180) or 180))
    station = db.get(ChargingStation, station_id)
    if station is None or station.condominium_id != current_user.condominium_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Station not found")

    session_count, total_energy_wh = station_totals(db, station_id=station.id)
    latest_session = station_latest_session(db, station_id=station.id)
    return StationResponse(
        id=station.id,
        host=station.host,
        vendor=station.vendor,
        name=station.name,
        created_at=station.created_at,
        updated_at=station.updated_at,
        session_count=session_count,
        total_energy_wh=total_energy_wh,
        latest_session=build_session_response(latest_session) if latest_session is not None else None,
        status=station.status,
        status_source=station.status_source,
        last_sync_at=station.last_sync_at,
        last_seen_at=station.last_seen_at,
        last_poll_at=station.last_poll_at,
        connector_status=station.connector_status,
        charging_state=station.charging_state,
        status_is_fresh=_status_is_fresh(station=station, stale_after_seconds=stale_after),
        active_session=False,
        active_session_source="last_sync",
    )
