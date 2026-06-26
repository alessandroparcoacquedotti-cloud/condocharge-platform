from __future__ import annotations

import socket
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter
from sqlalchemy import func, select

from condocharge.api.deps import AdminUser, DbSession
from condocharge.api.v1.dashboard import _build_agent_status
from condocharge.core.config import DEFAULT_PRODUCTION_CORS_ORIGINS, get_settings
from condocharge.models.tenancy import AppUser, PushSubscription
from condocharge.schemas.system_health import SystemHealthResponse

router = APIRouter(prefix="/admin/system", tags=["admin-system"])


def _railway_host_hint() -> str:
    settings = get_settings()
    public_url = settings.public_url.strip().rstrip("/")
    if public_url:
        parsed = urlparse(public_url)
        if parsed.hostname:
            return parsed.hostname

    for origin in DEFAULT_PRODUCTION_CORS_ORIGINS:
        parsed = urlparse(origin)
        if parsed.hostname:
            return parsed.hostname

    return "shimmering-quietude-production.up.railway.app"


@router.get("/health", response_model=SystemHealthResponse, summary="Admin system health snapshot")
def admin_system_health(db: DbSession, admin_user: AdminUser) -> SystemHealthResponse:
    now = datetime.now(tz=UTC)
    database_ok = True
    try:
        db.execute(select(1)).one()
    except Exception:
        database_ok = False

    railway_dns_ok = True
    try:
        socket.getaddrinfo(_railway_host_hint(), 443)
    except Exception:
        railway_dns_ok = False

    settings = get_settings()
    telegram_configured = bool(settings.telegram_bot_token.strip() and settings.telegram_bot_username.strip())
    push_configured = bool(settings.web_push_enabled)

    push_active_subscriptions = int(
        db.scalar(
            select(func.count(PushSubscription.id))
            .join(AppUser, AppUser.id == PushSubscription.user_id)
            .where(AppUser.condominium_id == admin_user.condominium_id)
            .where(PushSubscription.active == 1)
        )
        or 0
    )

    agent_status = _build_agent_status(db=db, condominium_id=admin_user.condominium_id, now=now)

    return SystemHealthResponse(
        server_time=now,
        backend_ok=True,
        database_ok=database_ok,
        railway_dns_ok=railway_dns_ok,
        telegram_configured=telegram_configured,
        push_configured=push_configured,
        push_active_subscriptions=push_active_subscriptions,
        agent_status=agent_status,
    )
