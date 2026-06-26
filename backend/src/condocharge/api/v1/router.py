from __future__ import annotations

from fastapi import APIRouter

from condocharge.api.v1.admin import router as admin_router
from condocharge.api.v1.admin_email import router as admin_email_router
from condocharge.api.v1.admin_notifications import router as admin_notifications_router
from condocharge.api.v1.admin_queue import router as admin_queue_router
from condocharge.api.v1.admin_system_health import router as admin_system_health_router
from condocharge.api.v1.admin_telegram import router as admin_telegram_router
from condocharge.api.v1.agent import router as agent_router
from condocharge.api.v1.auth import router as auth_router
from condocharge.api.v1.billing_admin import router as billing_admin_router
from condocharge.api.v1.billing_resident import router as billing_resident_router
from condocharge.api.v1.dashboard import router as dashboard_router
from condocharge.api.v1.push import router as push_router
from condocharge.api.v1.resident import router as resident_router
from condocharge.api.v1.resident_queue import router as resident_queue_router
from condocharge.api.v1.sessions import router as sessions_router
from condocharge.api.v1.stations import router as stations_router
from condocharge.api.v1.telegram import router as telegram_router
from condocharge.api.v1.users import router as users_router

router = APIRouter(prefix="/v1")
router.include_router(auth_router)
router.include_router(agent_router)
router.include_router(admin_router)
router.include_router(admin_email_router)
router.include_router(admin_notifications_router)
router.include_router(admin_queue_router)
router.include_router(admin_system_health_router)
router.include_router(admin_telegram_router)
router.include_router(billing_admin_router)
router.include_router(billing_resident_router)
router.include_router(push_router)
router.include_router(resident_router)
router.include_router(resident_queue_router)
router.include_router(stations_router)
router.include_router(sessions_router)
router.include_router(telegram_router)
router.include_router(users_router)
router.include_router(dashboard_router)
