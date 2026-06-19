from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from condocharge.api.deps import AdminUser
from condocharge.app.services.telegram_bot_service import TelegramBotService, TelegramDeliveryError
from condocharge.core.config import get_settings
from condocharge.schemas.telegram import (
    AdminTelegramStatusResponse,
    AdminTelegramTestSendRequest,
    AdminTelegramTestSendResponse,
)

router = APIRouter(prefix="/admin/telegram", tags=["admin-telegram"])


@router.get("/status", response_model=AdminTelegramStatusResponse, summary="Check Telegram bot health")
def telegram_status(admin_user: AdminUser) -> AdminTelegramStatusResponse:
    del admin_user
    settings = get_settings()
    bot_service = TelegramBotService(settings=settings)
    result = bot_service.check_health()
    return AdminTelegramStatusResponse(
        status=result.status,
        configured=result.configured,
        bot_username=result.bot_username,
        webhook_path="/api/v1/telegram/webhook",
        message=result.message,
    )


@router.post("/test-send", response_model=AdminTelegramTestSendResponse, summary="Send or preview a Telegram test message")
def telegram_test_send(admin_user: AdminUser, body: AdminTelegramTestSendRequest) -> AdminTelegramTestSendResponse:
    settings = get_settings()
    bot_service = TelegramBotService(settings=settings)
    generated_at = datetime.now(tz=UTC).isoformat()
    preview = (
        f"CondoCharge Telegram test\n"
        f"Condominium: {admin_user.condominium.name}\n"
        f"Generated at: {generated_at}"
    )

    if not bot_service.enabled:
        return AdminTelegramTestSendResponse(
            chat_id=body.chat_id,
            delivery_status="preview",
            telegram_enabled=False,
            message_preview=preview,
            provider_message_id=None,
        )

    try:
        result = bot_service.send_message(chat_id=body.chat_id, text=preview)
    except TelegramDeliveryError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Telegram delivery failed: {exc}") from exc

    return AdminTelegramTestSendResponse(
        chat_id=body.chat_id,
        delivery_status="sent",
        telegram_enabled=True,
        message_preview=preview,
        provider_message_id=result.message_id,
    )
