from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from condocharge.api.deps import AdminUser
from condocharge.app.services.telegram_bot_service import TelegramBotService, TelegramDeliveryError
from condocharge.app.services.telegram_notification_service import (
    NOTIFICATION_TYPE_AGENT_OFFLINE,
    NOTIFICATION_TYPE_AGENT_RECOVERED,
    NOTIFICATION_TYPE_CHARGING_COMPLETED,
    NOTIFICATION_TYPE_STATION_AVAILABLE,
    NOTIFICATION_TYPE_STATION_BACK_ONLINE,
    NOTIFICATION_TYPE_STATION_BUSY,
    ResidentTelegramNotificationService,
)
from condocharge.core.config import get_settings
from condocharge.db.session import SessionLocal
from condocharge.models.tenancy import AppUser, AppUserRole
from condocharge.schemas.telegram import (
    AdminTelegramSimulationRequest,
    AdminTelegramSimulationResponse,
    AdminTelegramStatusResponse,
    AdminTelegramTestSendRequest,
    AdminTelegramTestSendResponse,
)

router = APIRouter(prefix="/admin/telegram", tags=["admin-telegram"])
_SIMULATABLE_TYPES = {
    NOTIFICATION_TYPE_STATION_AVAILABLE,
    NOTIFICATION_TYPE_STATION_BUSY,
    NOTIFICATION_TYPE_CHARGING_COMPLETED,
    NOTIFICATION_TYPE_STATION_BACK_ONLINE,
    NOTIFICATION_TYPE_AGENT_OFFLINE,
    NOTIFICATION_TYPE_AGENT_RECOVERED,
}


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


@router.post(
    "/simulate",
    response_model=AdminTelegramSimulationResponse,
    summary="Trigger a real Telegram notification simulation for a linked resident",
)
def telegram_simulate(admin_user: AdminUser, body: AdminTelegramSimulationRequest) -> AdminTelegramSimulationResponse:
    if body.notification_type not in _SIMULATABLE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported notification type")

    db = SessionLocal()
    try:
        resident = db.scalar(
            select(AppUser)
            .where(AppUser.id == body.resident_app_user_id)
            .where(AppUser.condominium_id == admin_user.condominium_id)
            .where(AppUser.role == AppUserRole.RESIDENT.value)
            .where(AppUser.is_active == 1)
            .limit(1)
        )
        if resident is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resident not found")
        if not (resident.telegram_chat_id or "").strip():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Resident is not linked to Telegram")

        settings = get_settings()
        bot_service = TelegramBotService(settings=settings)
        service = ResidentTelegramNotificationService(db=db, settings=settings, bot_service=bot_service)
        row = service.send_admin_simulation(
            condominium_id=admin_user.condominium_id,
            resident=resident,
            notification_type=body.notification_type,
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Simulation could not be created")

        preview = (
            f"Notification: {body.notification_type}\n"
            f"Resident: {resident.username}\n"
            f"Generated at: {datetime.now(tz=UTC).isoformat()}"
        )
        return AdminTelegramSimulationResponse(
            resident_app_user_id=resident.id,
            resident_username=resident.username,
            notification_type=body.notification_type,
            delivery_status=row.status,
            telegram_enabled=bot_service.enabled,
            provider_message_id=row.provider_message_id,
            audit_id=row.id,
            audit_status=row.status,
            message_preview=preview,
        )
    finally:
        db.close()
