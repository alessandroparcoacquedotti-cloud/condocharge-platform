from __future__ import annotations

import sys
from datetime import datetime, timezone
from threading import Lock

import httpx
from fastapi import APIRouter, HTTPException, Path, Query, status
from sqlalchemy import select

from condocharge.api.deps import CurrentUser, DbSession, NonResidentUser
from condocharge.api.v1._helpers import build_session_response, paginate, station_latest_session, station_totals
from condocharge.app.integrations.base.models import ConnectorStatus, StationAvailability, StationTarget, StationVendor
from condocharge.app.integrations.legrand.driver import LegrandGreenUpDriver
from condocharge.core.config import get_settings
from condocharge.models.charging import ChargingStation
from condocharge.schemas.api import StationListResponse, StationOccupancyListResponse, StationOccupancyResponse, StationResponse


router = APIRouter(prefix="/stations", tags=["stations"])

_live_driver_lock = Lock()
_live_driver = LegrandGreenUpDriver(
    timeout=httpx.Timeout(connect=3.0, read=7.5, write=7.5, pool=7.5),
    max_retries=1,
)
_live_driver_hosts: set[str] = set()


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
    now = datetime.now(tz=timezone.utc)
    if credentials is None:
        return StationOccupancyResponse(
            station_id=station.id,
            host=station.host,
            connector_status=None,
            computed_status="offline",
            last_checked_at=now,
        )

    try:
        username, password = credentials
        with _live_driver_lock:
            if station.host not in _live_driver_hosts:
                _live_driver.login(station.host, username, password)
                _live_driver_hosts.add(station.host)
            status = _live_driver.get_station_status(station.host)
        observed_at = datetime.now(tz=timezone.utc)
        connector = status.connector_status or ConnectorStatus.UNKNOWN

        if connector in (ConnectorStatus.CHARGING, ConnectorStatus.OCCUPIED):
            computed = "charging"
        elif connector == ConnectorStatus.AVAILABLE:
            computed = "available"
        else:
            computed = "available"

        return StationOccupancyResponse(
            station_id=station.id,
            host=station.host,
            connector_status=str(connector),
            computed_status=computed,
            last_checked_at=observed_at,
        )
    except Exception:
        return StationOccupancyResponse(
            station_id=station.id,
            host=station.host,
            connector_status=None,
            computed_status="offline",
            last_checked_at=now,
        )


def _stations_live_occupancy(
    *,
    stations: list[ChargingStation],
    credentials: tuple[str, str] | None,
) -> list[StationOccupancyResponse]:
    if not stations:
        return []
    return [_station_occupancy_snapshot(station=s, credentials=credentials) for s in stations]


@router.get(
    "",
    response_model=StationListResponse,
    summary="List charging stations",
    description="Returns imported charging stations with pagination and aggregate energy/session counters.",
)
def list_stations(
    db: DbSession,
    current_user: NonResidentUser,
    limit: int = Query(default=50, ge=1, le=200, description="Maximum number of stations to return"),
    offset: int = Query(default=0, ge=0, description="Number of stations to skip"),
) -> StationListResponse:
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
                active_session=False,
                active_session_source="last_sync",
            )
        )
    return StationListResponse(items=items, pagination=pagination)


@router.get(
    "/occupancy",
    response_model=StationOccupancyListResponse,
    summary="Get live station occupancy (available/charging/offline)",
    description="Retrieves current connector status via the Legrand integration. Read-only and does not modify the database.",
)
def station_occupancy(
    db: DbSession,
    current_user: NonResidentUser,
) -> StationOccupancyListResponse:
    credentials = _resolve_legrand_credentials()

    stations = db.scalars(
        select(ChargingStation)
        .where(ChargingStation.condominium_id == current_user.condominium_id)
        .order_by(ChargingStation.id.asc())
    ).all()
    items = _stations_live_occupancy(stations=stations, credentials=credentials)
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
        active_session=False,
        active_session_source="last_sync",
    )
