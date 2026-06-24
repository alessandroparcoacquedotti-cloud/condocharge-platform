from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from condocharge.models.queue import (
    QUEUE_ENTRY_STATUS_LEFT,
    QUEUE_ENTRY_STATUS_OFFERED,
    QUEUE_ENTRY_STATUS_WAITING,
    ChargingQueueEntry,
    ChargingQueueSettings,
)
from condocharge.models.tenancy import AppUser
from condocharge.schemas.queue import AdminQueueSettingsResponse, ResidentQueueStatusResponse


class QueueDisabledError(RuntimeError):
    pass


class QueueService:
    def __init__(self, *, db: Session) -> None:
        self._db = db

    def get_or_create_settings(self, *, condominium_id: int) -> ChargingQueueSettings:
        row = self._db.scalar(
            select(ChargingQueueSettings)
            .where(ChargingQueueSettings.condominium_id == condominium_id)
            .limit(1)
        )
        if row is not None:
            return row

        row = ChargingQueueSettings(condominium_id=condominium_id, queue_enabled=0)
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def get_admin_settings(self, *, condominium_id: int) -> AdminQueueSettingsResponse:
        settings = self.get_or_create_settings(condominium_id=condominium_id)
        return AdminQueueSettingsResponse(
            queue_enabled=bool(settings.queue_enabled),
            waiting_count=self._waiting_count(condominium_id=condominium_id),
            updated_at=settings.updated_at,
        )

    def update_admin_settings(self, *, condominium_id: int, queue_enabled: bool) -> AdminQueueSettingsResponse:
        settings = self.get_or_create_settings(condominium_id=condominium_id)
        settings.queue_enabled = 1 if queue_enabled else 0
        self._db.commit()
        self._db.refresh(settings)
        return AdminQueueSettingsResponse(
            queue_enabled=bool(settings.queue_enabled),
            waiting_count=self._waiting_count(condominium_id=condominium_id),
            updated_at=settings.updated_at,
        )

    def get_resident_status(self, *, resident: AppUser) -> ResidentQueueStatusResponse:
        settings = self.get_or_create_settings(condominium_id=resident.condominium_id)
        active_entry = self._active_entry(resident=resident)
        return ResidentQueueStatusResponse(
            queue_enabled=bool(settings.queue_enabled),
            in_queue=active_entry is not None,
            position=self._position_for_entry(active_entry) if active_entry is not None else None,
            joined_at=active_entry.joined_at if active_entry is not None else None,
            active_entry_id=active_entry.id if active_entry is not None else None,
            status=active_entry.status if active_entry is not None else None,
        )

    def join_queue(self, *, resident: AppUser) -> ResidentQueueStatusResponse:
        settings = self.get_or_create_settings(condominium_id=resident.condominium_id)
        if not settings.queue_enabled:
            raise QueueDisabledError("Queue is disabled")

        active_entry = self._active_entry(resident=resident)
        if active_entry is not None:
            return self.get_resident_status(resident=resident)

        # TODO: Block joins while a resident is actively charging once a reliable resident-to-live-session
        # signal exists in the platform. Current v1.2.0 foundation keeps join behavior non-blocking.
        now = datetime.now(tz=UTC)
        row = ChargingQueueEntry(
            condominium_id=resident.condominium_id,
            resident_app_user_id=resident.id,
            status=QUEUE_ENTRY_STATUS_WAITING,
            joined_at=now,
        )
        self._db.add(row)
        self._db.commit()
        return self.get_resident_status(resident=resident)

    def leave_queue(self, *, resident: AppUser) -> ResidentQueueStatusResponse:
        active_entry = self._active_entry(resident=resident)
        if active_entry is None:
            return self.get_resident_status(resident=resident)

        active_entry.status = QUEUE_ENTRY_STATUS_LEFT
        active_entry.reserved_station_id = None
        active_entry.reserved_at = None
        active_entry.reservation_expires_at = None
        active_entry.left_at = datetime.now(tz=UTC)
        active_entry.leave_reason = "resident_left"
        self._db.commit()
        return self.get_resident_status(resident=resident)

    def is_queue_enabled(self, *, condominium_id: int) -> bool:
        return bool(self.get_or_create_settings(condominium_id=condominium_id).queue_enabled)

    def active_count(self, *, condominium_id: int) -> int:
        return int(
            self._db.scalar(
                select(func.count())
                .select_from(ChargingQueueEntry)
                .where(ChargingQueueEntry.condominium_id == condominium_id)
                .where(ChargingQueueEntry.status.in_(self._active_statuses()))
            )
            or 0
        )

    def active_reservation_count(self, *, condominium_id: int) -> int:
        return int(
            self._db.scalar(
                select(func.count())
                .select_from(ChargingQueueEntry)
                .where(ChargingQueueEntry.condominium_id == condominium_id)
                .where(ChargingQueueEntry.status == QUEUE_ENTRY_STATUS_OFFERED)
            )
            or 0
        )

    def has_active_entries(self, *, condominium_id: int) -> bool:
        return self.active_count(condominium_id=condominium_id) > 0

    def promote_waiting_entries(
        self,
        *,
        condominium_id: int,
        station_ids: list[int],
        reserved_at: datetime,
        reservation_expires_at: datetime,
    ) -> list[ChargingQueueEntry]:
        if not station_ids or not self.is_queue_enabled(condominium_id=condominium_id):
            return []

        offered_station_ids = set(
            self._db.scalars(
                select(ChargingQueueEntry.reserved_station_id)
                .where(ChargingQueueEntry.condominium_id == condominium_id)
                .where(ChargingQueueEntry.status == QUEUE_ENTRY_STATUS_OFFERED)
                .where(ChargingQueueEntry.reserved_station_id.is_not(None))
            ).all()
        )
        free_station_ids = [station_id for station_id in station_ids if station_id not in offered_station_ids]
        if not free_station_ids:
            return []

        waiting_rows = (
            self._db.scalars(
                select(ChargingQueueEntry)
                .where(ChargingQueueEntry.condominium_id == condominium_id)
                .where(ChargingQueueEntry.status == QUEUE_ENTRY_STATUS_WAITING)
                .order_by(ChargingQueueEntry.joined_at.asc(), ChargingQueueEntry.id.asc())
                .limit(len(free_station_ids))
            ).all()
        )
        if not waiting_rows:
            return []

        rows: list[ChargingQueueEntry] = []
        for station_id, row in zip(free_station_ids, waiting_rows, strict=False):
            row.status = QUEUE_ENTRY_STATUS_OFFERED
            row.reserved_station_id = station_id
            row.reserved_at = reserved_at
            row.reservation_expires_at = reservation_expires_at
            row.left_at = None
            row.leave_reason = None
            rows.append(row)
        self._db.commit()
        for row in rows:
            self._db.refresh(row)
        return rows

    def get_offered_entry_for_station(
        self,
        *,
        condominium_id: int,
        station_id: int,
    ) -> ChargingQueueEntry | None:
        return self._db.scalar(
            select(ChargingQueueEntry)
            .where(ChargingQueueEntry.condominium_id == condominium_id)
            .where(ChargingQueueEntry.status == QUEUE_ENTRY_STATUS_OFFERED)
            .where(ChargingQueueEntry.reserved_station_id == station_id)
            .order_by(ChargingQueueEntry.reserved_at.asc(), ChargingQueueEntry.id.asc())
            .limit(1)
        )

    def mark_started_reservation(
        self,
        *,
        entry: ChargingQueueEntry,
        started_at: datetime,
    ) -> ChargingQueueEntry:
        entry.status = QUEUE_ENTRY_STATUS_LEFT
        entry.reserved_station_id = None
        entry.reserved_at = None
        entry.reservation_expires_at = None
        entry.left_at = started_at
        entry.leave_reason = "charging_started"
        self._db.commit()
        self._db.refresh(entry)
        return entry

    def cancel_offered_reservation(
        self,
        *,
        entry: ChargingQueueEntry,
        cancelled_at: datetime,
        reason: str,
    ) -> ChargingQueueEntry:
        entry.status = QUEUE_ENTRY_STATUS_LEFT
        entry.reserved_station_id = None
        entry.reserved_at = None
        entry.reservation_expires_at = None
        entry.left_at = cancelled_at
        entry.leave_reason = reason
        self._db.commit()
        self._db.refresh(entry)
        return entry

    def expire_overdue_reservations(
        self,
        *,
        now: datetime,
        condominium_id: int | None = None,
    ) -> list[ChargingQueueEntry]:
        query = (
            select(ChargingQueueEntry)
            .where(ChargingQueueEntry.status == QUEUE_ENTRY_STATUS_OFFERED)
            .where(ChargingQueueEntry.reservation_expires_at.is_not(None))
            .where(ChargingQueueEntry.reservation_expires_at <= now)
            .order_by(ChargingQueueEntry.reservation_expires_at.asc(), ChargingQueueEntry.id.asc())
        )
        if condominium_id is not None:
            query = query.where(ChargingQueueEntry.condominium_id == condominium_id)
        rows = list(self._db.scalars(query).all())
        if not rows:
            return []

        for row in rows:
            row.status = QUEUE_ENTRY_STATUS_LEFT
            row.reserved_station_id = None
            row.reserved_at = None
            row.reservation_expires_at = None
            row.left_at = now
            row.leave_reason = "reservation_expired"
        self._db.commit()
        for row in rows:
            self._db.refresh(row)
        return rows

    def _active_entry(self, *, resident: AppUser) -> ChargingQueueEntry | None:
        return self._db.scalar(
            select(ChargingQueueEntry)
            .where(ChargingQueueEntry.condominium_id == resident.condominium_id)
            .where(ChargingQueueEntry.resident_app_user_id == resident.id)
            .where(ChargingQueueEntry.status.in_(self._active_statuses()))
            .order_by(ChargingQueueEntry.joined_at.asc(), ChargingQueueEntry.id.asc())
            .limit(1)
        )

    def _waiting_count(self, *, condominium_id: int) -> int:
        return int(
            self._db.scalar(
                select(func.count())
                .select_from(ChargingQueueEntry)
                .where(ChargingQueueEntry.condominium_id == condominium_id)
                .where(ChargingQueueEntry.status == QUEUE_ENTRY_STATUS_WAITING)
            )
            or 0
        )

    def _position_for_entry(self, entry: ChargingQueueEntry) -> int:
        position = int(
            self._db.scalar(
                select(func.count())
                .select_from(ChargingQueueEntry)
                .where(ChargingQueueEntry.condominium_id == entry.condominium_id)
                .where(ChargingQueueEntry.status.in_(self._active_statuses()))
                .where(
                    or_(
                        ChargingQueueEntry.joined_at < entry.joined_at,
                        and_(
                            ChargingQueueEntry.joined_at == entry.joined_at,
                            ChargingQueueEntry.id <= entry.id,
                        ),
                    )
                )
            )
            or 0
        )
        return max(position, 1)

    @staticmethod
    def _active_statuses() -> tuple[str, ...]:
        return (QUEUE_ENTRY_STATUS_WAITING, QUEUE_ENTRY_STATUS_OFFERED)
