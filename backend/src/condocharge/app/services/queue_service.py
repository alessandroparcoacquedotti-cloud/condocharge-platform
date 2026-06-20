from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from condocharge.models.queue import (
    QUEUE_ENTRY_STATUS_LEFT,
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
        active_entry = self._active_waiting_entry(resident=resident)
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

        active_entry = self._active_waiting_entry(resident=resident)
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
        active_entry = self._active_waiting_entry(resident=resident)
        if active_entry is None:
            return self.get_resident_status(resident=resident)

        active_entry.status = QUEUE_ENTRY_STATUS_LEFT
        active_entry.left_at = datetime.now(tz=UTC)
        active_entry.leave_reason = "resident_left"
        self._db.commit()
        return self.get_resident_status(resident=resident)

    def _active_waiting_entry(self, *, resident: AppUser) -> ChargingQueueEntry | None:
        return self._db.scalar(
            select(ChargingQueueEntry)
            .where(ChargingQueueEntry.condominium_id == resident.condominium_id)
            .where(ChargingQueueEntry.resident_app_user_id == resident.id)
            .where(ChargingQueueEntry.status == QUEUE_ENTRY_STATUS_WAITING)
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
                .where(ChargingQueueEntry.status == QUEUE_ENTRY_STATUS_WAITING)
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
