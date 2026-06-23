from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import select

from condocharge.api.deps import DbSession
from condocharge.api.v1._helpers import session_detail_query
from condocharge.api.v1.stations import (
    _resolve_legrand_credentials,
    _stations_db_occupancy,
    _stations_hybrid_occupancy,
    _stations_live_occupancy,
)
from condocharge.app.services.resident_telegram_link_service import ResidentTelegramLinkService, TelegramLinkError
from condocharge.app.services.queue_service import QueueDisabledError, QueueService
from condocharge.app.services.telegram_bot_service import TelegramBotService, TelegramDeliveryError, TelegramSendResult
from condocharge.app.services.telegram_notification_service import ResidentTelegramNotificationService
from condocharge.core.config import get_settings
from condocharge.models.charging import ChargingSession, ChargingStation, RfidUser
from condocharge.models.tenancy import AppUser, AppUserRole

router = APIRouter(prefix="/telegram", tags=["telegram"])

_KNOWN_COMMANDS = {"/start", "/help", "/status", "/test", "/history"}
_BUTTON_JOIN_QUEUE = "Entra in coda"
_BUTTON_LEAVE_QUEUE = "Esci dalla coda"
_BUTTON_VIEW_POSITION = "Posizione"
_BUTTON_REGULATIONS = "Regolamento"
_BUTTON_ACTIONS = {
    _BUTTON_JOIN_QUEUE: "join_queue",
    _BUTTON_LEAVE_QUEUE: "leave_queue",
    _BUTTON_VIEW_POSITION: "view_position",
    _BUTTON_REGULATIONS: "regulations",
}
_ROME_TZ = ZoneInfo("Europe/Rome")


def _send_message_best_effort(
    *,
    bot_service: TelegramBotService,
    chat_id: str,
    text: str,
    reply_markup: dict[str, Any] | None = None,
) -> TelegramSendResult | None:
    if not bot_service.enabled:
        return None
    try:
        if reply_markup is None:
            return bot_service.send_message(chat_id=chat_id, text=text)
        else:
            try:
                return bot_service.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
            except TypeError:
                return bot_service.send_message(chat_id=chat_id, text=text)
    except TelegramDeliveryError:
        return None
    return None


def _pin_message_best_effort(
    *,
    bot_service: TelegramBotService,
    chat_id: str,
    message_id: str | None,
) -> None:
    if not bot_service.enabled or not message_id:
        return
    try:
        bot_service.pin_message(chat_id=chat_id, message_id=message_id)
    except TelegramDeliveryError:
        return


def _send_regulations_best_effort(
    *,
    bot_service: TelegramBotService,
    chat_id: str,
    condominium_name: str,
) -> None:
    result = _send_message_best_effort(
        bot_service=bot_service,
        chat_id=chat_id,
        text=_queue_regulations_message(condominium_name=condominium_name),
        reply_markup=_queue_keyboard(),
    )
    _pin_message_best_effort(
        bot_service=bot_service,
        chat_id=chat_id,
        message_id=result.message_id if result is not None else None,
    )


def _format_local_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(_ROME_TZ).strftime("%Y-%m-%d %H:%M")


def _normalize_command(text: str, *, bot_username: str | None) -> tuple[str, str | None]:
    parts = text.split(maxsplit=1)
    command_part = (parts[0] if parts else "").strip()
    command_name = command_part.split("@", maxsplit=1)[0].lower()
    if bot_username and "@" in command_part:
        command_target = command_part.split("@", maxsplit=1)[1].strip().lstrip("@").lower()
        if command_target and command_target != bot_username.strip().lstrip("@").lower():
            return "", None
    argument = parts[1].strip() if len(parts) == 2 and parts[1].strip() else None
    return command_name, argument


def _unknown_chat_instructions(*, bot_username: str | None) -> str:
    handle = f"@{bot_username}" if bot_username else "@CondoChargeBot"
    return (
        "CondoCharge Telegram non e ancora collegato.\n\n"
        "1. Accedi al tuo profilo residente su CondoCharge.\n"
        "2. Apri la sezione Telegram.\n"
        "3. Premi 'Genera link Telegram'.\n"
        f"4. Apri il bot {handle} dal link generato.\n\n"
        "Dopo il collegamento potrai usare /help, /status, /history e /test."
    )


def _help_message(*, condominium_name: str) -> str:
    return (
        "🔌 CondoCharge\n\n"
        f"Condominio: {condominium_name}\n\n"
        "Comandi disponibili:\n"
        "/help - mostra questo riepilogo\n"
        "/status - stato attuale delle colonnine del tuo condominio\n"
        "/history - ultime 10 sessioni di ricarica\n"
        "/test - invia una notifica Telegram di test e registra un audit\n"
        "/start - conferma il collegamento o mostra le istruzioni iniziali"
    )


def _queue_keyboard() -> dict[str, Any]:
    return {
        "keyboard": [
            [{"text": _BUTTON_JOIN_QUEUE}, {"text": _BUTTON_LEAVE_QUEUE}],
            [{"text": _BUTTON_VIEW_POSITION}, {"text": _BUTTON_REGULATIONS}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


def _queue_regulations_message(*, condominium_name: str) -> str:
    return (
        "📜 Regolamento CondoCharge\n\n"
        f"Condominio: {condominium_name}\n\n"
        "• Le assegnazioni seguono l'ordine della coda.\n"
        "• Hai 30 minuti per iniziare la ricarica.\n"
        "• Se non inizi entro il tempo previsto perdi il turno.\n"
        "• Quando la ricarica termina, libera il posto appena possibile.\n"
        "• Le prenotazioni sono attive dalle 08:00 alle 22:00.\n"
        "• Le informazioni degli altri residenti non sono visibili."
    )


def _status_icon(computed_status: str) -> str:
    if computed_status == "free":
        return "🟢"
    if computed_status == "busy":
        return "🔴"
    return "⚫"


def _status_label(computed_status: str) -> str:
    if computed_status == "free":
        return "Libera"
    if computed_status == "busy":
        return "Occupata"
    return "Non disponibile"


def _linked_resident_by_chat(*, db: DbSession, chat_id: str) -> AppUser | None:
    return db.scalar(
        select(AppUser)
        .where(AppUser.telegram_chat_id == chat_id)
        .where(AppUser.role == AppUserRole.RESIDENT.value)
        .where(AppUser.is_active == 1)
        .limit(1)
    )


def _is_recent_timestamp(*, value: datetime | None, settings) -> bool:
    if value is None:
        return False
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    stale_after_seconds = max(1, int(getattr(settings, "agent_stale_after_seconds", 180) or 180))
    return value.astimezone(UTC) >= datetime.now(tz=UTC) - timedelta(seconds=stale_after_seconds)


def _format_kwh_from_wh(energy_wh: int) -> str:
    return f"{(int(energy_wh) / 1000.0):.3f}".rstrip("0").rstrip(".") or "0"


def _format_eur(amount: float) -> str:
    return f"{amount:.2f}"


def _status_message_for_resident(*, db: DbSession, resident: AppUser) -> str:
    settings = get_settings()
    stations = db.scalars(
        select(ChargingStation)
        .where(ChargingStation.condominium_id == resident.condominium_id)
        .order_by(ChargingStation.id.asc())
    ).all()
    if not stations:
        return (
            "🔌 CondoCharge\n\n"
            f"Condominio: {resident.condominium.name}\n\n"
            "Nessuna colonnina configurata."
        )

    if settings.normalized_agent_occupancy_source == "db":
        occupancy = _stations_db_occupancy(
            db=db,
            stations=stations,
            transition_source="telegram_status",
            transition_reason="telegram /status",
        )
    elif settings.normalized_agent_occupancy_source == "live_only":
        occupancy = _stations_live_occupancy(
            db=db,
            stations=stations,
            credentials=_resolve_legrand_credentials(),
            transition_source="telegram_status",
            transition_reason="telegram /status",
        )
    else:
        occupancy = _stations_hybrid_occupancy(
            db=db,
            stations=stations,
            credentials=_resolve_legrand_credentials(),
            stale_after_seconds=max(1, int(getattr(settings, "agent_stale_after_seconds", 180) or 180)),
            transition_source="telegram_status",
            transition_reason="telegram /status",
        )
    db.flush()

    latest_checked = max((item.last_checked_at for item in occupancy), default=None)
    free_count = sum(1 for item in occupancy if item.computed_status == "free")
    busy_count = sum(1 for item in occupancy if item.computed_status == "busy")
    unavailable_count = len(occupancy) - free_count - busy_count
    lines = [
        "🔌 CondoCharge",
        "",
        f"Condominio: {resident.condominium.name}",
        "",
        f"Riepilogo disponibilita: {free_count} libera/e, {busy_count} occupata/e, {unavailable_count} non disponibile/i",
        "",
    ]

    by_station_id = {item.station_id: item for item in occupancy}
    for station in stations:
        item = by_station_id.get(station.id)
        if item is None:
            continue
        lines.append(f"{station.name or station.host}: {_status_icon(item.computed_status)} {_status_label(item.computed_status)}")
        reason_raw = getattr(item, "unavailable_reason", None)
        reason = str(reason_raw).strip() if reason_raw is not None else ""
        if item.computed_status == "unavailable" and reason:
            lines.append(f"Motivo: {reason}")

    lines.extend(
        [
            "",
            (
                f"Ultimo aggiornamento: {_format_local_dt(latest_checked)}"
                if _is_recent_timestamp(value=latest_checked, settings=settings)
                else "Ultimo aggiornamento: dati in aggiornamento"
            ),
        ]
    )
    queue_status = QueueService(db=db).get_resident_status(resident=resident)
    lines.extend(["", "Coda"])
    if not queue_status.queue_enabled:
        lines.append("Stato: non attiva")
    elif queue_status.status == "offered":
        lines.append("Stato: turno assegnato")
    elif queue_status.in_queue and queue_status.position is not None:
        lines.append(f"Posizione in coda: {queue_status.position}")
    else:
        lines.append("Stato: non sei in coda")
    return "\n".join(lines)


def _queue_status_message(*, db: DbSession, resident: AppUser) -> str:
    status_row = QueueService(db=db).get_resident_status(resident=resident)
    if not status_row.queue_enabled:
        return "La coda non e attiva in questo momento."
    if status_row.status == "offered":
        return "🟢 E il tuo turno.\n\nHai 30 minuti per iniziare la ricarica."
    if status_row.in_queue and status_row.position is not None:
        return f"Posizione in coda: {status_row.position}"
    return "Non sei attualmente in coda."


def _history_message_for_resident(*, db: DbSession, resident: AppUser) -> str:
    sessions = (
        db.scalars(
            session_detail_query()
            .join(ChargingSession.rfid_user)
            .where(ChargingSession.condominium_id == resident.condominium_id)
            .where(RfidUser.app_user_id == resident.id)
            .order_by(ChargingSession.end_time.desc(), ChargingSession.id.desc())
            .limit(10)
        )
        .unique()
        .all()
    )
    if not sessions:
        return "📊 Storico consumi\n\nNessuna sessione di ricarica registrata."

    price = float(resident.condominium.energy_price_eur_per_kwh)
    lines = ["📊 Storico consumi", "", "Ultime 10 sessioni di ricarica:"]
    for session in sessions:
        estimated_cost = round((int(session.energy_wh) / 1000.0) * price, 2)
        lines.append(
            f"{_format_local_dt(session.end_time)} - {_format_kwh_from_wh(int(session.energy_wh))} kWh - €{_format_eur(estimated_cost)}"
        )
    return "\n".join(lines)


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
    if not text or not chat_id:
        return {"ok": True}

    action = _BUTTON_ACTIONS.get(text)
    command = ""
    argument = None
    if action is None:
        if not text.startswith("/"):
            return {"ok": True}
        command, argument = _normalize_command(text, bot_username=settings.telegram_bot_username)
    if action is None and command not in _KNOWN_COMMANDS:
        return {"ok": True}

    bot_service = TelegramBotService(settings=settings)
    resident = _linked_resident_by_chat(db=db, chat_id=chat_id)
    link_service = ResidentTelegramLinkService(
        db=db,
        settings=settings,
        deep_link_builder=lambda issued_token: bot_service.build_deep_link(token=issued_token),
    )
    if command == "/start" and argument:
        try:
            resident = link_service.link_chat(
                token=argument,
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

    if resident is None:
        _send_message_best_effort(
            bot_service=bot_service,
            chat_id=chat_id,
            text=_unknown_chat_instructions(bot_username=settings.telegram_bot_username.strip().lstrip("@") or None),
        )
        return {"ok": True}

    if command in {"/start", "/help"}:
        _send_message_best_effort(
            bot_service=bot_service,
            chat_id=chat_id,
            text=_help_message(condominium_name=resident.condominium.name),
        )
        if command == "/start":
            _send_regulations_best_effort(
                bot_service=bot_service,
                chat_id=chat_id,
                condominium_name=resident.condominium.name,
            )
        return {"ok": True}

    if action == "join_queue":
        service = QueueService(db=db)
        try:
            service.join_queue(resident=resident)
            text_out = _queue_status_message(db=db, resident=resident)
        except QueueDisabledError:
            text_out = "Queue is currently disabled by the administrator."
        _send_message_best_effort(
            bot_service=bot_service,
            chat_id=chat_id,
            text=text_out,
            reply_markup=_queue_keyboard(),
        )
        return {"ok": True}

    if action == "leave_queue":
        service = QueueService(db=db)
        text_out = _queue_status_message(db=db, resident=resident)
        if service.get_resident_status(resident=resident).in_queue:
            service.leave_queue(resident=resident)
            text_out = _queue_status_message(db=db, resident=resident)
        _send_message_best_effort(
            bot_service=bot_service,
            chat_id=chat_id,
            text=text_out,
            reply_markup=_queue_keyboard(),
        )
        return {"ok": True}

    if action == "view_position":
        _send_message_best_effort(
            bot_service=bot_service,
            chat_id=chat_id,
            text=_queue_status_message(db=db, resident=resident),
            reply_markup=_queue_keyboard(),
        )
        return {"ok": True}

    if action == "regulations":
        _send_regulations_best_effort(
            bot_service=bot_service,
            chat_id=chat_id,
            condominium_name=resident.condominium.name,
        )
        return {"ok": True}

    if command == "/status":
        text_out = _status_message_for_resident(db=db, resident=resident)
        db.commit()
        _send_message_best_effort(
            bot_service=bot_service,
            chat_id=chat_id,
            text=text_out,
            reply_markup=_queue_keyboard(),
        )
        return {"ok": True}

    if command == "/history":
        _send_message_best_effort(
            bot_service=bot_service,
            chat_id=chat_id,
            text=_history_message_for_resident(db=db, resident=resident),
        )
        return {"ok": True}

    if command == "/test":
        notification_service = ResidentTelegramNotificationService(db=db, settings=settings, bot_service=bot_service)
        notification_service.send_command_test(
            condominium_id=resident.condominium_id,
            resident=resident,
        )
    return {"ok": True}
