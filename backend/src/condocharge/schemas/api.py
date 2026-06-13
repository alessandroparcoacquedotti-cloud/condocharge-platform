from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PaginationMeta(BaseModel):
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class StationRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    host: str
    vendor: str
    name: str | None = None


class ResidentStationRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None = None


class RfidUserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rfid_id: str
    name: str | None = None


class SessionResponse(BaseModel):
    id: int
    source_key: str
    station_id: int
    rfid_user_id: int | None = None
    start_time: datetime
    end_time: datetime
    energy_wh: int
    total_minutes: int
    charging_minutes: int
    idle_minutes: int
    plug_type: str | None = None
    created_at: datetime
    updated_at: datetime
    station: StationRef | None = None
    rfid_user: RfidUserRef | None = None


class ResidentSessionResponse(BaseModel):
    id: int
    source_key: str
    station_id: int
    rfid_user_id: int | None = None
    start_time: datetime
    end_time: datetime
    energy_wh: int
    total_minutes: int
    charging_minutes: int
    idle_minutes: int
    plug_type: str | None = None
    created_at: datetime
    updated_at: datetime
    station: ResidentStationRef | None = None
    rfid_user: RfidUserRef | None = None


class SessionListResponse(BaseModel):
    items: list[SessionResponse]
    pagination: PaginationMeta


class ResidentSessionListResponse(BaseModel):
    items: list[ResidentSessionResponse]
    pagination: PaginationMeta


class StationResponse(BaseModel):
    id: int
    host: str
    vendor: str
    name: str | None = None
    created_at: datetime
    updated_at: datetime
    session_count: int = 0
    total_energy_wh: int = 0
    latest_session: SessionResponse | None = None
    status: str | None = None
    status_source: str | None = None
    last_sync_at: datetime | None = None
    active_session: bool | None = None
    active_session_source: str | None = None


class StationOccupancyResponse(BaseModel):
    station_id: int
    host: str
    connector_status: str | None = None
    computed_status: str
    last_checked_at: datetime


class StationOccupancyListResponse(BaseModel):
    items: list[StationOccupancyResponse]


class ResidentStationOccupancyResponse(BaseModel):
    station_id: int
    computed_status: str
    last_checked_at: datetime


class ResidentStationOccupancyListResponse(BaseModel):
    items: list[ResidentStationOccupancyResponse]


class StationListResponse(BaseModel):
    items: list[StationResponse]
    pagination: PaginationMeta


class UserResponse(BaseModel):
    id: int
    rfid_id: str
    name: str | None = None
    created_at: datetime
    updated_at: datetime
    session_count: int = 0
    total_energy_wh: int = 0
    latest_session: SessionResponse | None = None


class UserListResponse(BaseModel):
    items: list[UserResponse]
    pagination: PaginationMeta


class TopUserByEnergyResponse(BaseModel):
    user_id: int
    rfid_id: str
    name: str | None = None
    total_energy_wh: int
    total_energy_kwh: float
    session_count: int


class DashboardSummaryResponse(BaseModel):
    total_sessions: int
    total_energy_wh: int
    total_energy_kwh: float
    total_users: int
    total_stations: int
    latest_session: SessionResponse | None = None
    top_users_by_energy: list[TopUserByEnergyResponse]


class ResidentStationLastCharge(BaseModel):
    end_time: datetime
    energy_wh: int
    total_minutes: int


class ResidentStationStatusResponse(BaseModel):
    id: int
    name: str | None = None
    known_status: str | None = None
    last_sync_at: datetime | None = None
    last_charge: ResidentStationLastCharge | None = None


class ResidentStationStatusListResponse(BaseModel):
    items: list[ResidentStationStatusResponse]
