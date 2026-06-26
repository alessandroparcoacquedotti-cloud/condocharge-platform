from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from condocharge.api.deps import AgentPrincipal
from condocharge.app.services.station_state_mapper import map_agent_station_state
from condocharge.models.charging import AgentState, ChargingSession, ChargingStation, RfidUser
from condocharge.models.tenancy import AppUser
from condocharge.schemas.agent import (
    AgentHeartbeatRequest,
    AgentSessionRow,
    AgentSessionsImportRequest,
    AgentStationStatusBatchRequest,
)


@dataclass
class StatusIngestionResult:
    updated: int = 0
    rejected: int = 0
    items: list[tuple[str, str, datetime]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class SessionsIngestionResult:
    sessions_imported: int = 0
    sessions_updated: int = 0
    duplicates_ignored: int = 0
    hosts_processed: int = 0
    errors: list[str] = field(default_factory=list)


class AgentIngestionService:
    def __init__(self, *, db: Session) -> None:
        self._db = db

    def record_heartbeat(self, *, agent: AgentPrincipal, body: AgentHeartbeatRequest) -> None:
        state = self._get_or_create_agent_state(agent=agent)
        now = datetime.now(tz=UTC)
        state.hostname = body.hostname.strip()
        state.agent_version = body.agent_version.strip()
        state.agent_started_at = body.started_at.astimezone(UTC)
        state.last_heartbeat_at = now
        state.last_heartbeat_sent_at = body.sent_at.astimezone(UTC)
        state.heartbeat_count = int(body.heartbeat_count)
        state.polling_count = int(body.polling_count)
        state.import_count = int(body.import_count)
        state.retry_count = int(body.retry_count)
        state.failure_count = int(body.failure_count)
        self._db.commit()

    def ingest_status_batch(self, *, agent: AgentPrincipal, body: AgentStationStatusBatchRequest) -> StatusIngestionResult:
        result = StatusIngestionResult(updated=0, rejected=0)
        hosts = [s.host.strip() for s in body.stations]
        stations = self._db.scalars(
            select(ChargingStation)
            .where(ChargingStation.condominium_id == agent.condominium_id)
            .where(ChargingStation.host.in_(hosts))
        ).all()
        by_host = {s.host: s for s in stations}

        for item in body.stations:
            station = by_host.get(item.host)
            if station is None:
                result.rejected += 1
                result.errors.append(f"{item.host}: unknown station host for condominium {agent.condominium_id}")
                continue

            mapped = map_agent_station_state(item)
            station.last_poll_at = item.observed_at.astimezone(UTC)
            if item.reachable:
                station.last_seen_at = item.observed_at.astimezone(UTC)
            station.last_error = mapped.last_error
            station.connector_status = mapped.connector_status
            station.rfid_enabled = mapped.rfid_enabled
            station.charging_state = mapped.charging_state
            station.last_status_payload_json = json.dumps(item.last_status_payload) if item.last_status_payload is not None else None
            station.status = mapped.status
            station.status_source = "agent"
            result.updated += 1
            result.items.append((station.host, station.status, station.last_poll_at))

        state = self._get_or_create_agent_state(agent=agent)
        state.last_station_update_at = datetime.now(tz=UTC)
        self._db.commit()
        return result

    def ingest_sessions_import(self, *, agent: AgentPrincipal, body: AgentSessionsImportRequest) -> SessionsIngestionResult:
        result = SessionsIngestionResult()
        for host_item in body.hosts:
            host = host_item.host.strip()
            station = self._db.scalar(
                select(ChargingStation)
                .where(ChargingStation.host == host)
                .where(ChargingStation.condominium_id == agent.condominium_id)
            )
            if station is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"errors": [f"{host}: unknown station host for condominium {agent.condominium_id}"]},
                )
            result.hosts_processed += 1

            for session in host_item.sessions:
                self._upsert_session(
                    agent=agent,
                    station=station,
                    host=host,
                    session=session,
                    result=result,
                )

            station.last_sync_at = datetime.now(tz=UTC)
            station.status_source = station.status_source or "agent"

        state = self._get_or_create_agent_state(agent=agent)
        state.last_session_import_at = datetime.now(tz=UTC)
        self._db.commit()

        return result

    def _get_or_create_agent_state(self, *, agent: AgentPrincipal) -> AgentState:
        state = self._db.scalar(
            select(AgentState)
            .where(AgentState.condominium_id == agent.condominium_id)
            .where(AgentState.agent_id == agent.agent_id)
        )
        if state is not None:
            return state

        state = AgentState(
            condominium_id=agent.condominium_id,
            agent_id=agent.agent_id,
        )
        self._db.add(state)
        self._db.flush()
        return state

    def _upsert_session(
        self,
        *,
        agent: AgentPrincipal,
        station: ChargingStation,
        host: str,
        session: AgentSessionRow,
        result: SessionsIngestionResult,
    ) -> None:
        start_time = session.start_time.astimezone(UTC)
        end_time = session.end_time.astimezone(UTC)
        source_key = self._source_key(host=host, start_time=start_time, end_time=end_time, energy_wh=int(session.energy_wh))

        rfid_user_id: int | None = None
        if session.rfid_id and session.rfid_id.strip():
            rfid_user = self._upsert_rfid_user(
                condominium_id=agent.condominium_id,
                rfid_id=session.rfid_id.strip(),
                rfid_name=session.rfid_name.strip() if session.rfid_name else None,
            )
            rfid_user_id = rfid_user.id

        existing = self._db.scalar(select(ChargingSession).where(ChargingSession.source_key == source_key))
        if existing is None:
            row = ChargingSession(
                condominium_id=agent.condominium_id,
                source_key=source_key,
                station_id=station.id,
                rfid_user_id=rfid_user_id,
                start_time=start_time,
                end_time=end_time,
                energy_wh=int(session.energy_wh),
                total_minutes=int(session.total_minutes),
                charging_minutes=int(session.charging_minutes),
                idle_minutes=int(session.idle_minutes),
                plug_type=session.plug_type,
            )
            try:
                with self._db.begin_nested():
                    self._db.add(row)
                    self._db.flush()
                result.sessions_imported += 1
                return
            except IntegrityError:
                self._db.rollback()
                existing = self._db.scalar(select(ChargingSession).where(ChargingSession.source_key == source_key))
                if existing is None:
                    raise

        existing_start = self._coerce_dt(existing.start_time)
        existing_end = self._coerce_dt(existing.end_time)
        changed = False
        if existing.station_id != station.id:
            existing.station_id = station.id
            changed = True
        if existing.rfid_user_id != rfid_user_id:
            existing.rfid_user_id = rfid_user_id
            changed = True
        if existing_start != start_time:
            existing.start_time = start_time
            changed = True
        if existing_end != end_time:
            existing.end_time = end_time
            changed = True
        if existing.energy_wh != int(session.energy_wh):
            existing.energy_wh = int(session.energy_wh)
            changed = True
        if existing.total_minutes != int(session.total_minutes):
            existing.total_minutes = int(session.total_minutes)
            changed = True
        if existing.charging_minutes != int(session.charging_minutes):
            existing.charging_minutes = int(session.charging_minutes)
            changed = True
        if existing.idle_minutes != int(session.idle_minutes):
            existing.idle_minutes = int(session.idle_minutes)
            changed = True
        if existing.plug_type != session.plug_type:
            existing.plug_type = session.plug_type
            changed = True

        if changed:
            result.sessions_updated += 1
        else:
            result.duplicates_ignored += 1

    def _upsert_rfid_user(self, *, condominium_id: int, rfid_id: str, rfid_name: str | None) -> RfidUser:
        user = self._db.scalar(select(RfidUser).where(RfidUser.rfid_id == rfid_id))
        if user is None:
            user = RfidUser(condominium_id=condominium_id, rfid_id=rfid_id, name=rfid_name)
            self._db.add(user)
            self._db.flush()
            self._auto_link_rfid_user(condominium_id=condominium_id, rfid_user=user, candidates=[rfid_name, rfid_id])
            return user
        if user.condominium_id != condominium_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="RFID user is assigned to a different condominium")

        if rfid_name and user.name != rfid_name:
            user.name = rfid_name
        self._auto_link_rfid_user(condominium_id=condominium_id, rfid_user=user, candidates=[rfid_name, rfid_id])
        return user

    def _auto_link_rfid_user(self, *, condominium_id: int, rfid_user: RfidUser, candidates: list[str | None]) -> None:
        if rfid_user.app_user_id is not None:
            return
        values = [c.strip() for c in candidates if c and c.strip()]
        for value in values:
            match = self._db.scalar(
                select(AppUser)
                .where(AppUser.condominium_id == condominium_id)
                .where(AppUser.role.in_(("resident", "admin", "viewer")))
                .where(AppUser.is_active == 1)
                .where(AppUser.username.ilike(value))
                .limit(1)
            )
            if match is not None:
                rfid_user.app_user_id = match.id
                return

    @staticmethod
    def _source_key(*, host: str, start_time: datetime, end_time: datetime, energy_wh: int) -> str:
        payload = "|".join([host, start_time.isoformat(), end_time.isoformat(), str(int(energy_wh))])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _coerce_dt(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
