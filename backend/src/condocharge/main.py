from __future__ import annotations

import logging
from threading import Event, Thread

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from condocharge.api.router import api_router
from condocharge.app.services.resident_notification_service import (
    StationAvailabilityNotificationPoller,
)
from condocharge.app.services.push_notification_service import (
    PushAgentStatusNotificationPoller,
    PushStationNotificationPoller,
)
from condocharge.app.services.telegram_notification_service import (
    TelegramAgentStatusNotificationPoller,
    TelegramStationAvailabilityNotificationPoller,
)
from condocharge.core.config import get_settings
from condocharge.db.session import (
    RESOLVED_DATABASE_URL,
    RESOLVED_SQLITE_PATH,
    SessionLocal,
    sanitize_database_url_for_logs,
    sanitize_sqlite_path_for_logs,
)
from condocharge.models.tenancy import AppUser, Condominium


def create_app() -> FastAPI:
    settings = get_settings()
    settings.validate_runtime_settings()
    app = FastAPI(title="CondoCharge", version="0.1.0")

    cors_origins = settings.effective_cors_origin_strings
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Cache-Control"],
        )

    app.include_router(api_router)

    @app.on_event("startup")
    def _startup_log() -> None:
        logger = logging.getLogger("uvicorn.error")

        active_condominiums: int | None = None
        active_users: int | None = None
        try:
            with SessionLocal() as db:
                active_condominiums = int(
                    db.scalar(select(func.count()).select_from(Condominium).where(Condominium.is_active == 1)) or 0
                )
                active_users = int(
                    db.scalar(
                        select(func.count())
                        .select_from(AppUser)
                        .join(Condominium, Condominium.id == AppUser.condominium_id)
                        .where(AppUser.is_active == 1)
                        .where(Condominium.is_active == 1)
                    )
                    or 0
                )
        except Exception:
            logger.exception("Startup DB inspection failed")

        logger.info(
            "startup database_url=%s resolved_database_url=%s sqlite_path=%s active_condominiums=%s active_users=%s",
            sanitize_database_url_for_logs(settings.database_url),
            sanitize_database_url_for_logs(RESOLVED_DATABASE_URL),
            sanitize_sqlite_path_for_logs(RESOLVED_SQLITE_PATH),
            active_condominiums,
            active_users,
        )

        if settings.notifications_enabled:
            stop_event = Event()
            email_poller = StationAvailabilityNotificationPoller(
                db_factory=SessionLocal,
                settings=settings,
            )
            thread = Thread(
                target=_run_notification_poller,
                args=(email_poller, stop_event, settings.notification_poll_interval_seconds),
                name="condocharge-notification-poller",
                daemon=True,
            )
            thread.start()
            app.state.notification_poller_stop_event = stop_event
            app.state.notification_poller_thread = thread
            logger.info(
                "resident notification poller enabled interval_seconds=%s",
                settings.notification_poll_interval_seconds,
            )

            push_stop_event = Event()
            push_station_poller = PushStationNotificationPoller(
                db_factory=SessionLocal,
                settings=settings,
            )
            push_agent_poller = PushAgentStatusNotificationPoller(
                db_factory=SessionLocal,
                settings=settings,
            )
            push_station_thread = Thread(
                target=_run_notification_poller,
                args=(push_station_poller, push_stop_event, settings.notification_poll_interval_seconds),
                name="condocharge-push-station-poller",
                daemon=True,
            )
            push_agent_thread = Thread(
                target=_run_notification_poller,
                args=(push_agent_poller, push_stop_event, settings.notification_poll_interval_seconds),
                name="condocharge-push-agent-poller",
                daemon=True,
            )
            push_station_thread.start()
            push_agent_thread.start()
            app.state.push_notification_poller_stop_event = push_stop_event
            app.state.push_station_poller_thread = push_station_thread
            app.state.push_agent_poller_thread = push_agent_thread
            logger.info(
                "push notification pollers enabled interval_seconds=%s web_push_enabled=%s",
                settings.notification_poll_interval_seconds,
                settings.web_push_enabled,
            )

            if settings.telegram_bot_token.strip():
                telegram_stop_event = Event()
                telegram_station_poller = TelegramStationAvailabilityNotificationPoller(
                    db_factory=SessionLocal,
                    settings=settings,
                )
                telegram_agent_poller = TelegramAgentStatusNotificationPoller(
                    db_factory=SessionLocal,
                    settings=settings,
                )
                station_thread = Thread(
                    target=_run_notification_poller,
                    args=(telegram_station_poller, telegram_stop_event, settings.notification_poll_interval_seconds),
                    name="condocharge-telegram-station-poller",
                    daemon=True,
                )
                agent_thread = Thread(
                    target=_run_notification_poller,
                    args=(telegram_agent_poller, telegram_stop_event, settings.notification_poll_interval_seconds),
                    name="condocharge-telegram-agent-poller",
                    daemon=True,
                )
                station_thread.start()
                agent_thread.start()
                app.state.telegram_notification_poller_stop_event = telegram_stop_event
                app.state.telegram_station_poller_thread = station_thread
                app.state.telegram_agent_poller_thread = agent_thread
                logger.info(
                    "telegram notification pollers enabled interval_seconds=%s",
                    settings.notification_poll_interval_seconds,
                )

    @app.on_event("shutdown")
    def _shutdown_notification_poller() -> None:
        stop_event: Event | None = getattr(app.state, "notification_poller_stop_event", None)
        thread: Thread | None = getattr(app.state, "notification_poller_thread", None)
        if stop_event is None or thread is None:
            stop_event = None
        if stop_event is not None:
            stop_event.set()
        if thread is not None:
            thread.join(timeout=5)

        telegram_stop_event: Event | None = getattr(app.state, "telegram_notification_poller_stop_event", None)
        station_thread: Thread | None = getattr(app.state, "telegram_station_poller_thread", None)
        agent_thread: Thread | None = getattr(app.state, "telegram_agent_poller_thread", None)
        if telegram_stop_event is not None:
            telegram_stop_event.set()
        if station_thread is not None:
            station_thread.join(timeout=5)
        if agent_thread is not None:
            agent_thread.join(timeout=5)

        push_stop_event: Event | None = getattr(app.state, "push_notification_poller_stop_event", None)
        push_station_thread: Thread | None = getattr(app.state, "push_station_poller_thread", None)
        push_agent_thread: Thread | None = getattr(app.state, "push_agent_poller_thread", None)
        if push_stop_event is not None:
            push_stop_event.set()
        if push_station_thread is not None:
            push_station_thread.join(timeout=5)
        if push_agent_thread is not None:
            push_agent_thread.join(timeout=5)
    return app


app = create_app()


def _run_notification_poller(
    poller: object,
    stop_event: Event,
    interval_seconds: int,
) -> None:
    logger = logging.getLogger("uvicorn.error")
    wait_seconds = max(interval_seconds, 1)
    while not stop_event.is_set():
        try:
            getattr(poller, "poll_once")()
        except Exception:
            logger.exception("Resident notification poller failed")
        stop_event.wait(wait_seconds)
