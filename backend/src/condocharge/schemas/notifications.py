from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from condocharge.schemas.api import PaginationMeta


class AdminNotificationLogRow(BaseModel):
    id: int
    created_at: datetime
    sent_at: datetime | None = None
    condominium_id: int
    resident_app_user_id: int
    resident_username: str
    resident_email: str | None = None
    notification_type: str
    dedupe_key: str
    status: str
    error_message: str | None = None


class AdminNotificationLogListResponse(BaseModel):
    items: list[AdminNotificationLogRow]
    pagination: PaginationMeta
