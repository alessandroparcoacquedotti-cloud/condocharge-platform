from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TelegramLinkStatusResponse(BaseModel):
    linked: bool
    chat_id: str | None = None
    telegram_username: str | None = None
    linked_at: datetime | None = None


class TelegramLinkIssueResponse(BaseModel):
    expires_at: datetime
    deep_link_url: str | None = None
    bot_username: str | None = None


class AdminTelegramStatusResponse(BaseModel):
    status: str
    configured: bool
    bot_username: str | None = None
    webhook_path: str
    message: str | None = None


class AdminTelegramTestSendRequest(BaseModel):
    chat_id: str = Field(min_length=1, max_length=64)


class AdminTelegramTestSendResponse(BaseModel):
    chat_id: str
    delivery_status: str
    telegram_enabled: bool
    message_preview: str
    provider_message_id: str | None = None
