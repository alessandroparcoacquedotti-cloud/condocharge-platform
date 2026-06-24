from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from condocharge.api.deps import CurrentAgent, DbSession
from condocharge.app.services.agent_ingestion_service import AgentIngestionService
from condocharge.schemas.agent import (
    AgentHeartbeatRequest,
    AgentHeartbeatResponse,
    AgentSessionsImportRequest,
    AgentSessionsImportResponse,
    AgentStationStatusAck,
    AgentStationStatusBatchRequest,
    AgentStationStatusBatchResponse,
)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/heartbeat", response_model=AgentHeartbeatResponse, summary="Agent heartbeat")
def heartbeat(db: DbSession, current_agent: CurrentAgent, body: AgentHeartbeatRequest) -> AgentHeartbeatResponse:
    service = AgentIngestionService(db=db)
    service.record_heartbeat(agent=current_agent, body=body)
    now = datetime.now(tz=UTC)
    return AgentHeartbeatResponse(
        agent_id=current_agent.agent_id,
        received_at=now,
        server_time=now,
    )


@router.post(
    "/stations/status/batch",
    response_model=AgentStationStatusBatchResponse,
    summary="Ingest station status batch from local agent",
)
def ingest_station_status(
    db: DbSession,
    current_agent: CurrentAgent,
    body: AgentStationStatusBatchRequest,
) -> AgentStationStatusBatchResponse:
    service = AgentIngestionService(db=db)
    outcome = service.ingest_status_batch(agent=current_agent, body=body)
    now = datetime.now(tz=UTC)
    items = [
        AgentStationStatusAck(host=host, status=status_value, status_source="agent", last_poll_at=last_poll_at)
        for host, status_value, last_poll_at in (outcome.items or [])
    ]
    return AgentStationStatusBatchResponse(
        agent_id=current_agent.agent_id,
        received_at=now,
        updated=outcome.updated,
        rejected=outcome.rejected,
        items=items,
    )


@router.post(
    "/sessions/import",
    response_model=AgentSessionsImportResponse,
    summary="Ingest session imports from local agent",
)
def ingest_sessions(
    db: DbSession,
    current_agent: CurrentAgent,
    body: AgentSessionsImportRequest,
) -> AgentSessionsImportResponse:
    service = AgentIngestionService(db=db)
    outcome = service.ingest_sessions_import(agent=current_agent, body=body)
    now = datetime.now(tz=UTC)
    return AgentSessionsImportResponse(
        agent_id=current_agent.agent_id,
        received_at=now,
        sessions_imported=outcome.sessions_imported,
        sessions_updated=outcome.sessions_updated,
        duplicates_ignored=outcome.duplicates_ignored,
        hosts_processed=outcome.hosts_processed,
        errors=outcome.errors or [],
    )
