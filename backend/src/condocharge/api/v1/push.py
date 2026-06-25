from __future__ import annotations

from fastapi import APIRouter

from condocharge.api.deps import CurrentUser, DbSession
from condocharge.app.services.push_notification_service import PushNotificationService
from condocharge.core.config import get_settings
from condocharge.schemas.push import (
    PushSubscriptionRequest,
    PushSubscriptionStatusResponse,
    PushTestResponse,
)

router = APIRouter(prefix="/push", tags=["push"])


@router.post(
    "/subscribe",
    response_model=PushSubscriptionStatusResponse,
    summary="Subscribe the current device to web push notifications",
)
def subscribe_push(
    db: DbSession,
    current_user: CurrentUser,
    body: PushSubscriptionRequest,
) -> PushSubscriptionStatusResponse:
    settings = get_settings()
    service = PushNotificationService(db=db, settings=settings)
    subscribed, active_count = service.upsert_subscription(
        user=current_user,
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
    )
    return PushSubscriptionStatusResponse(
        subscribed=subscribed,
        active_subscriptions=active_count,
        web_push_enabled=settings.web_push_enabled,
    )


@router.post(
    "/unsubscribe",
    response_model=PushSubscriptionStatusResponse,
    summary="Unsubscribe the current device from web push notifications",
)
def unsubscribe_push(
    db: DbSession,
    current_user: CurrentUser,
    body: PushSubscriptionRequest,
) -> PushSubscriptionStatusResponse:
    settings = get_settings()
    service = PushNotificationService(db=db, settings=settings)
    subscribed, active_count = service.deactivate_subscription(
        user=current_user,
        endpoint=body.endpoint,
    )
    return PushSubscriptionStatusResponse(
        subscribed=subscribed,
        active_subscriptions=active_count,
        web_push_enabled=settings.web_push_enabled,
    )


@router.post(
    "/test",
    response_model=PushTestResponse,
    summary="Send a test web push notification to the current user",
)
def test_push(
    db: DbSession,
    current_user: CurrentUser,
) -> PushTestResponse:
    settings = get_settings()
    service = PushNotificationService(db=db, settings=settings)
    result = service.send_test(user=current_user)
    return PushTestResponse(
        delivery_status=result.status,
        push_enabled=settings.web_push_enabled,
        delivered_count=result.delivered_count,
        message_preview="Test notifiche CondoCharge",
    )
