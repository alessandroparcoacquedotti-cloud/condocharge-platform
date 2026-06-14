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
            poller = StationAvailabilityNotificationPoller(
                db_factory=SessionLocal,
                settings=settings,
            )
            thread = Thread(
                target=_run_notification_poller,
                args=(poller, stop_event, settings.notification_poll_interval_seconds),
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

    @app.on_event("shutdown")
    def _shutdown_notification_poller() -> None:
        stop_event: Event | None = getattr(app.state, "notification_poller_stop_event", None)
        thread: Thread | None = getattr(app.state, "notification_poller_thread", None)
        if stop_event is None or thread is None:
            return
        stop_event.set()
        thread.join(timeout=5)
    return app


app = create_app()


def _run_notification_poller(
    poller: StationAvailabilityNotificationPoller,
    stop_event: Event,
    interval_seconds: int,
) -> None:
    logger = logging.getLogger("uvicorn.error")
    wait_seconds = max(interval_seconds, 1)
    while not stop_event.is_set():
        try:
            poller.poll_once()
        except Exception:
            logger.exception("Resident notification poller failed")
        stop_event.wait(wait_seconds)
