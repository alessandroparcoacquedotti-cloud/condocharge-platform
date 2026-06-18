from __future__ import annotations

from dataclasses import dataclass

from condocharge.schemas.agent import AgentChargingState, AgentConnectorStatus, AgentStationStatusItem


@dataclass(frozen=True)
class MappedStationState:
    status: str
    connector_status: str | None
    rfid_enabled: bool | None
    charging_state: str | None
    last_error: str | None


def map_agent_station_state(item: AgentStationStatusItem) -> MappedStationState:
    if not item.reachable:
        return MappedStationState(
            status="offline",
            connector_status=str(item.connector_status),
            rfid_enabled=item.rfid_enabled,
            charging_state=str(item.charging_state),
            last_error=item.last_error or "unreachable",
        )

    connector = item.connector_status
    if connector == AgentConnectorStatus.CHARGING:
        status = "charging"
    elif connector == AgentConnectorStatus.OCCUPIED:
        status = "occupied"
    elif connector == AgentConnectorStatus.AVAILABLE:
        status = "available"
    else:
        if item.charging_state in {AgentChargingState.CHARGING}:
            status = "charging"
        else:
            status = "online"

    return MappedStationState(
        status=status,
        connector_status=str(connector),
        rfid_enabled=item.rfid_enabled,
        charging_state=str(item.charging_state),
        last_error=item.last_error,
    )

