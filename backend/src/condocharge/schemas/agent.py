from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AgentConnectorStatus(StrEnum):
    UNKNOWN = "unknown"
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    CHARGING = "charging"
    FAULTED = "faulted"
    UNAVAILABLE = "unavailable"


class AgentChargingState(StrEnum):
    UNKNOWN = "unknown"
    READY = "ready"
    CONNECTED = "connected"
    CHARGING = "charging"
    COMPLETE = "complete"
    FAULTED = "faulted"
    OFFLINE = "offline"


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware")
    return value


class AgentHeartbeatRequest(BaseModel):
    agent_version: str = Field(min_length=1)
    hostname: str = Field(min_length=1)
    started_at: datetime
    sent_at: datetime
    station_hosts: list[str] = Field(min_length=1)
    status_poll_interval_seconds: int = Field(ge=5)
    session_sync_interval_seconds: int = Field(ge=60)
    last_status_push_at: datetime | None = None
    last_session_import_at: datetime | None = None

    _started_at_aware = field_validator("started_at")(_require_aware_utc)
    _sent_at_aware = field_validator("sent_at")(_require_aware_utc)


class AgentHeartbeatResponse(BaseModel):
    ok: bool = True
    agent_id: str
    received_at: datetime
    server_time: datetime


class AgentStationStatusItem(BaseModel):
    host: str = Field(min_length=1)
    observed_at: datetime
    reachable: bool
    connector_status: AgentConnectorStatus = AgentConnectorStatus.UNKNOWN
    rfid_enabled: bool | None = None
    charging_state: AgentChargingState = AgentChargingState.UNKNOWN
    last_error: str | None = None
    last_status_payload: dict[str, Any] | None = None

    _observed_at_aware = field_validator("observed_at")(_require_aware_utc)


class AgentStationStatusBatchRequest(BaseModel):
    sent_at: datetime
    stations: list[AgentStationStatusItem] = Field(min_length=1, max_length=100)

    _sent_at_aware = field_validator("sent_at")(_require_aware_utc)

    @field_validator("stations")
    @classmethod
    def validate_unique_hosts(cls, value: list[AgentStationStatusItem]) -> list[AgentStationStatusItem]:
        seen: set[str] = set()
        for item in value:
            host = item.host.strip()
            if not host:
                raise ValueError("Host cannot be empty")
            if host in seen:
                raise ValueError(f"Duplicate host in batch: {host}")
            seen.add(host)
        return value


class AgentStationStatusAck(BaseModel):
    host: str
    status: str
    status_source: str
    last_poll_at: datetime | None = None


class AgentStationStatusBatchResponse(BaseModel):
    ok: bool = True
    agent_id: str
    received_at: datetime
    updated: int
    rejected: int
    items: list[AgentStationStatusAck]


class AgentSessionRow(BaseModel):
    start_time: datetime
    end_time: datetime
    energy_wh: int = Field(ge=0)
    total_minutes: int = Field(ge=0)
    charging_minutes: int = Field(ge=0)
    idle_minutes: int = Field(ge=0)
    plug_type: str | None = None
    rfid_id: str | None = None
    rfid_name: str | None = None

    _start_aware = field_validator("start_time")(_require_aware_utc)
    _end_aware = field_validator("end_time")(_require_aware_utc)

    @field_validator("end_time")
    @classmethod
    def validate_end_time(cls, end_time: datetime, info: Any) -> datetime:
        start_time: datetime | None = info.data.get("start_time")
        if start_time is not None and end_time < start_time:
            raise ValueError("end_time must be greater than or equal to start_time")
        return end_time


class AgentSessionsImportHost(BaseModel):
    host: str = Field(min_length=1)
    sessions: list[AgentSessionRow] = Field(default_factory=list, max_length=5000)


class AgentSessionsImportRequest(BaseModel):
    sent_at: datetime
    hosts: list[AgentSessionsImportHost] = Field(min_length=1, max_length=20)

    _sent_at_aware = field_validator("sent_at")(_require_aware_utc)

    @field_validator("hosts")
    @classmethod
    def validate_unique_hosts(cls, value: list[AgentSessionsImportHost]) -> list[AgentSessionsImportHost]:
        seen: set[str] = set()
        for item in value:
            host = item.host.strip()
            if not host:
                raise ValueError("Host cannot be empty")
            if host in seen:
                raise ValueError(f"Duplicate host in import: {host}")
            seen.add(host)
        return value


class AgentSessionsImportResponse(BaseModel):
    ok: bool = True
    agent_id: str
    received_at: datetime
    sessions_imported: int
    sessions_updated: int
    duplicates_ignored: int
    hosts_processed: int
    errors: list[str] = Field(default_factory=list)

