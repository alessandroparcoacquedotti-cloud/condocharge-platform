from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from condocharge.app.integrations.legrand.driver import (
    ChargingSession as LegrandChargingSession,
    LegrandGreenUpDriver,
)
from condocharge.app.services.resident_notification_service import ResidentNotificationService
from condocharge.core.config import Settings, get_settings
from condocharge.models.charging import ChargingSession, ChargingStation, RfidUser
from condocharge.models.tenancy import AppUser


@dataclass
class SessionSyncResult:
    sessions_imported: int = 0
    sessions_updated: int = 0
    total_sessions: int = 0
    total_energy_imported_wh: int = 0
    errors: list[str] = field(default_factory=list)


class SessionSyncService:
    def __init__(
        self,
        *,
        db: Session,
        driver: LegrandGreenUpDriver,
        settings: Settings | None = None,
        notification_service: ResidentNotificationService | None = None,
    ) -> None:
        self._db = db
        self._driver = driver
        self._settings = settings or get_settings()
        self._notification_service = notification_service or ResidentNotificationService(
            db=db,
            settings=self._settings,
        )

    def sync_hosts(
        self,
        *,
        condominium_id: int,
        hosts: list[str],
        username: str,
        password: str,
    ) -> SessionSyncResult:
        result = SessionSyncResult()
        for host in hosts:
            host = host.strip()
            if not host:
                continue
            try:
                self._sync_one_host(
                    condominium_id=condominium_id,
                    host=host,
                    username=username,
                    password=password,
                    result=result,
                )
            except Exception as exc:
                self._db.rollback()
                station = self._db.scalar(select(ChargingStation).where(ChargingStation.host == host))
                if station is not None:
                    station.status = "offline"
                    station.status_source = "last_sync"
                    station.last_sync_at = datetime.now(tz=timezone.utc)
                    self._db.commit()
                result.errors.append(f"{host}: {type(exc).__name__}: {exc}")
        result.total_sessions = (
            self._db.scalar(
                select(func.count()).select_from(ChargingSession).where(ChargingSession.condominium_id == condominium_id)
            )
            or 0
        )
        return result

    def _sync_one_host(
        self,
        *,
        condominium_id: int,
        host: str,
        username: str,
        password: str,
        result: SessionSyncResult,
    ) -> None:
        station = self._get_or_create_station(condominium_id=condominium_id, host=host)
        inserted_sessions: list[tuple[ChargingSession, RfidUser | None]] = []

        self._driver.login(host, username, password)
        sessions = self._driver.sync_charge_sessions(host)

        seen_source_keys: set[str] = set()
        for s in sessions:
            source_key = self._source_key(host=host, session=s)
            if source_key in seen_source_keys:
                continue
            seen_source_keys.add(source_key)

            rfid_user = self._upsert_rfid_user(condominium_id=condominium_id, session=s)
            existing = self._db.scalar(select(ChargingSession).where(ChargingSession.source_key == source_key))

            if existing is None:
                row = ChargingSession(
                    condominium_id=condominium_id,
                    source_key=source_key,
                    station_id=station.id,
                    rfid_user_id=rfid_user.id if rfid_user is not None else None,
                    start_time=self._normalize_dt(s.start_time),
                    end_time=self._normalize_dt(s.end_time),
                    energy_wh=int(s.energy_wh),
                    total_minutes=int(s.total_minutes),
                    charging_minutes=int(s.charging_minutes),
                    idle_minutes=int(s.idle_minutes),
                    plug_type=s.plug_type,
                )
                if self._try_insert_session(row):
                    result.sessions_imported += 1
                    result.total_energy_imported_wh += int(s.energy_wh)
                    inserted_sessions.append((row, rfid_user))
                    continue

                existing = self._find_existing_session(source_key=source_key, station_id=station.id, session=s)
                if existing is None:
                    raise IntegrityError("Duplicate session insert failed without a persisted matching row", params=None, orig=None)
                continue

            changed = self._apply_updates(existing, s, station_id=station.id, rfid_user_id=rfid_user.id if rfid_user else None)
            if changed:
                result.sessions_updated += 1

        self._db.commit()
        self._notify_inserted_sessions(inserted_sessions=inserted_sessions, result=result)
        station.status = "online"
        station.status_source = "last_sync"
        station.last_sync_at = datetime.now(tz=timezone.utc)
        self._db.commit()

    def _get_or_create_station(self, *, condominium_id: int, host: str) -> ChargingStation:
        existing = self._db.scalar(select(ChargingStation).where(ChargingStation.host == host))
        if existing is not None:
            if existing.condominium_id != condominium_id:
                raise ValueError("Station is assigned to a different condominium")
            return existing
        station = ChargingStation(condominium_id=condominium_id, host=host, vendor="legrand_greenup", name=None)
        self._db.add(station)
        self._db.flush()
        return station

    def _upsert_rfid_user(self, *, condominium_id: int, session: LegrandChargingSession) -> RfidUser | None:
        if session.rfid_id is None or session.rfid_id.strip() == "":
            return None

        rfid_id = session.rfid_id.strip()
        user = self._db.scalar(select(RfidUser).where(RfidUser.rfid_id == rfid_id))
        if user is None:
            user = RfidUser(condominium_id=condominium_id, rfid_id=rfid_id, name=session.rfid_name)
            self._db.add(user)
            self._db.flush()
            self._auto_link_rfid_user(condominium_id=condominium_id, rfid_user=user, session=session)
            return user
        if user.condominium_id != condominium_id:
            raise ValueError("RFID user is assigned to a different condominium")

        new_name = session.rfid_name.strip() if session.rfid_name else None
        if new_name and user.name != new_name:
            user.name = new_name
        self._auto_link_rfid_user(condominium_id=condominium_id, rfid_user=user, session=session)
        return user

    def _try_insert_session(self, row: ChargingSession) -> bool:
        try:
            with self._db.begin_nested():
                self._db.add(row)
                self._db.flush()
        except IntegrityError:
            return False
        return True

    def _find_existing_session(
        self,
        *,
        source_key: str,
        station_id: int,
        session: LegrandChargingSession,
    ) -> ChargingSession | None:
        existing = self._db.scalar(select(ChargingSession).where(ChargingSession.source_key == source_key))
        if existing is not None:
            return existing

        return self._db.scalar(
            select(ChargingSession)
            .where(ChargingSession.station_id == station_id)
            .where(ChargingSession.start_time == self._normalize_dt(session.start_time))
            .where(ChargingSession.end_time == self._normalize_dt(session.end_time))
            .where(ChargingSession.energy_wh == int(session.energy_wh))
        )

    def _auto_link_rfid_user(self, *, condominium_id: int, rfid_user: RfidUser, session: LegrandChargingSession) -> None:
        if rfid_user.app_user_id is not None:
            return

        candidates: list[str] = []
        if session.rfid_name and session.rfid_name.strip():
            candidates.append(session.rfid_name.strip())
        if session.rfid_id and session.rfid_id.strip():
            candidates.append(session.rfid_id.strip())

        for value in candidates:
            match = self._db.scalar(
                select(AppUser)
                .where(AppUser.condominium_id == condominium_id)
                .where(func.lower(AppUser.username) == func.lower(value))
                .where(AppUser.role.in_(("resident", "admin", "viewer")))
                .limit(1)
            )
            if match is not None:
                rfid_user.app_user_id = match.id
                return

    def _notify_inserted_sessions(
        self,
        *,
        inserted_sessions: list[tuple[ChargingSession, RfidUser | None]],
        result: SessionSyncResult,
    ) -> None:
        if not self._settings.notifications_enabled:
            return

        for row, rfid_user in inserted_sessions:
            if row.end_time is None or rfid_user is None or rfid_user.app_user_id is None:
                continue

            resident = self._db.get(AppUser, rfid_user.app_user_id)
            station = self._db.get(ChargingStation, row.station_id)
            if resident is None or station is None:
                continue

            try:
                self._notification_service.send_charging_completed(
                    session=row,
                    resident=resident,
                    station=station,
                )
            except Exception as exc:
                self._db.rollback()
                result.errors.append(
                    f"notification session_id={row.id}: {type(exc).__name__}: {exc}"
                )

    def _apply_updates(
        self,
        row: ChargingSession,
        session: LegrandChargingSession,
        *,
        station_id: int,
        rfid_user_id: int | None,
    ) -> bool:
        changed = False

        start_time = self._normalize_dt(session.start_time)
        end_time = self._normalize_dt(session.end_time)

        if row.station_id != station_id:
            row.station_id = station_id
            changed = True
        if row.rfid_user_id != rfid_user_id:
            row.rfid_user_id = rfid_user_id
            changed = True
        if row.start_time != start_time:
            row.start_time = start_time
            changed = True
        if row.end_time != end_time:
            row.end_time = end_time
            changed = True
        if row.energy_wh != int(session.energy_wh):
            row.energy_wh = int(session.energy_wh)
            changed = True
        if row.total_minutes != int(session.total_minutes):
            row.total_minutes = int(session.total_minutes)
            changed = True
        if row.charging_minutes != int(session.charging_minutes):
            row.charging_minutes = int(session.charging_minutes)
            changed = True
        if row.idle_minutes != int(session.idle_minutes):
            row.idle_minutes = int(session.idle_minutes)
            changed = True
        if row.plug_type != session.plug_type:
            row.plug_type = session.plug_type
            changed = True

        return changed

    def _normalize_dt(self, value: datetime) -> datetime:
        return value

    def _source_key(self, *, host: str, session: LegrandChargingSession) -> str:
        payload = "|".join(
            [
                host,
                session.start_time.isoformat(),
                session.end_time.isoformat(),
                str(int(session.energy_wh)),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
