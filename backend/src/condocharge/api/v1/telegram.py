from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, status

from condocharge.api.deps import DbSession
from condocharge.app.services.resident_telegram_link_service import ResidentTelegramLinkService, TelegramLinkError
from condocharge.app.services.telegram_bot_service import TelegramBotService, TelegramDeliveryError
from condocharge.core.config import get_settings

router = APIRouter(prefix="/telegram", tags=["telegram"])


def _send_message_best_effort(*, bot_service: TelegramBotService, chat_id: str, text: str) -> None:
    if not bot_service.enabled:
        return
    try:
        bot_service.send_message(chat_id=chat_id, text=text)
    except TelegramDeliveryError:
        return


@router.post("/webhook", summary="Telegram bot webhook")
def telegram_webhook(
    payload: dict[str, Any],
    db: DbSession,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    settings = get_settings()
    expected_secret = settings.telegram_webhook_secret.strip()
    if expected_secret and x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Telegram webhook secret")

    message = payload.get("message") or {}
    text = str(message.get("text") or "").strip()
    chat = message.get("chat") or {}
    from_user = message.get("from") or {}
    chat_id = str(chat.get("id") or "").strip()
    if not text.startswith("/start") or not chat_id:
        return {"ok": True}

    parts = text.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        return {"ok": True}

    token = parts[1].strip()
    bot_service = TelegramBotService(settings=settings)
    link_service = ResidentTelegramLinkService(
        db=db,
        settings=settings,
        deep_link_builder=lambda issued_token: bot_service.build_deep_link(token=issued_token),
    )
    try:
        resident = link_service.link_chat(
            token=token,
            chat_id=chat_id,
            telegram_username=(from_user.get("username") or None),
        )
        _send_message_best_effort(
            bot_service=bot_service,
            chat_id=chat_id,
            text=(
                f"CondoCharge linked successfully.\n"
                f"Resident: {resident.username}\n"
                f"You will now receive Telegram notifications."
            ),
        )
    except TelegramLinkError:
        _send_message_best_effort(
            bot_service=bot_service,
            chat_id=chat_id,
            text="CondoCharge link failed. The Telegram link is invalid or expired.",
        )
    return {"ok": True}
