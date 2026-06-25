from __future__ import annotations

from pydantic import BaseModel, Field


class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class PushSubscriptionRequest(BaseModel):
    endpoint: str = Field(min_length=1, max_length=1000)
    keys: PushSubscriptionKeys


class PushSubscriptionStatusResponse(BaseModel):
    subscribed: bool
    active_subscriptions: int
    web_push_enabled: bool


class PushTestResponse(BaseModel):
    delivery_status: str
    push_enabled: bool
    delivered_count: int
    message_preview: str


class ResidentPushStatusResponse(BaseModel):
    subscribed: bool
    active_subscriptions: int
    web_push_enabled: bool
