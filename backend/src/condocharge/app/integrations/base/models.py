from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class StationVendor(StrEnum):
    LEGRAND_GREENUP = "legrand_greenup"


class StationProtocol(StrEnum):
    REST = "rest"
    HTML_SCRAPING = "html_scraping"
    XML = "xml"
    MODBUS_TCP = "modbus_tcp"
    OCPP = "ocpp"
    CUSTOM = "custom"


class StationAvailability(StrEnum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"


class ConnectorStatus(StrEnum):
    UNKNOWN = "unknown"
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    CHARGING = "charging"
    FAULTED = "faulted"
    UNAVAILABLE = "unavailable"


class StationTarget(BaseModel):
    station_id: str
    name: str
    vendor: StationVendor
    host: str
    protocols_hint: list[StationProtocol] = Field(default_factory=list)


class StationIdentity(BaseModel):
    vendor: StationVendor
    model: str | None = None
    serial_number: str | None = None
    firmware_version: str | None = None


class ConnectorStatusSnapshot(BaseModel):
    connector_id: str
    status: ConnectorStatus = ConnectorStatus.UNKNOWN
    last_seen_at: datetime | None = None


class StationStatusSnapshot(BaseModel):
    station_id: str
    availability: StationAvailability = StationAvailability.UNKNOWN
    identity: StationIdentity | None = None
    connectors: list[ConnectorStatusSnapshot] = Field(default_factory=list)
    observed_at: datetime


class StationTelemetryPoint(BaseModel):
    station_id: str
    connector_id: str | None = None
    observed_at: datetime
    power_kw: float | None = None
    energy_kwh_total: float | None = None
    voltage_v: float | None = None
    current_a: float | None = None
    temperature_c: float | None = None
