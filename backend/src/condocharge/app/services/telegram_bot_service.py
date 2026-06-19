from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib import error, request

from condocharge.core.config import Settings


class TelegramDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramBotStatus:
    status: str
    configured: bool
    bot_username: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class TelegramSendResult:
    message_id: str


TelegramApiCaller = Callable[[str, dict[str, Any]], dict[str, Any]]


class TelegramBotService:
    def __init__(
        self,
        *,
        settings: Settings,
        api_caller: TelegramApiCaller | None = None,
    ) -> None:
        self._settings = settings
        self._api_caller = api_caller or self._call_api

    @property
    def enabled(self) -> bool:
        return bool(self._settings.telegram_bot_token.strip())

    def check_health(self) -> TelegramBotStatus:
        if not self.enabled:
            return TelegramBotStatus(
                status="disabled",
                configured=False,
                bot_username=self._settings.telegram_bot_username.strip() or None,
                message="Telegram bot token not configured.",
            )

        try:
            payload = self._api_caller("getMe", {})
        except TelegramDeliveryError as exc:
            return TelegramBotStatus(
                status="error",
                configured=True,
                bot_username=self._settings.telegram_bot_username.strip() or None,
                message=str(exc),
            )

        result = payload.get("result") or {}
        username = result.get("username") or self._settings.telegram_bot_username.strip() or None
        return TelegramBotStatus(status="ok", configured=True, bot_username=username, message=None)

    def build_deep_link(self, *, token: str) -> str | None:
        username = self._settings.telegram_bot_username.strip().lstrip("@")
        if not username:
            return None
        return f"https://t.me/{username}?start={token}"

    def send_message(self, *, chat_id: str, text: str) -> TelegramSendResult:
        if not self.enabled:
            raise TelegramDeliveryError("Telegram bot token not configured.")

        payload = self._api_caller(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
            },
        )
        result = payload.get("result") or {}
        message_id = result.get("message_id")
        if message_id is None:
            raise TelegramDeliveryError("Telegram API response did not include message_id.")
        return TelegramSendResult(message_id=str(message_id))

    def _call_api(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        token = self._settings.telegram_bot_token.strip()
        url = f"https://api.telegram.org/bot{token}/{method}"
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=max(self._settings.telegram_request_timeout_seconds, 1)) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TelegramDeliveryError(f"Telegram API HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise TelegramDeliveryError(f"Telegram API request failed: {exc.reason}") from exc

        try:
            payload_out = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TelegramDeliveryError("Telegram API returned invalid JSON.") from exc

        if not payload_out.get("ok", False):
            description = payload_out.get("description") or "Unknown Telegram API error."
            raise TelegramDeliveryError(str(description))
        return payload_out
