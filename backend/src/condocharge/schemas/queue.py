from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ResidentQueueStatusResponse(BaseModel):
    queue_enabled: bool
    in_queue: bool
    position: int | None = None
    joined_at: datetime | None = None
    active_entry_id: int | None = None
    status: str | None = None


class AdminQueueSettingsResponse(BaseModel):
    queue_enabled: bool
    waiting_count: int
    updated_at: datetime | None = None


class UpdateAdminQueueSettingsRequest(BaseModel):
    queue_enabled: bool = False
