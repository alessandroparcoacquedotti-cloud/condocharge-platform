from __future__ import annotations

from fastapi import APIRouter

from condocharge.api.deps import AdminUser, DbSession
from condocharge.app.services.queue_service import QueueService
from condocharge.schemas.queue import AdminQueueSettingsResponse, UpdateAdminQueueSettingsRequest

router = APIRouter(prefix="/admin/queue", tags=["admin-queue"])


@router.get(
    "/settings",
    response_model=AdminQueueSettingsResponse,
    summary="Get charging queue settings for the current condominium",
)
def get_queue_settings(db: DbSession, admin_user: AdminUser) -> AdminQueueSettingsResponse:
    service = QueueService(db=db)
    return service.get_admin_settings(condominium_id=admin_user.condominium_id)


@router.patch(
    "/settings",
    response_model=AdminQueueSettingsResponse,
    summary="Update charging queue settings for the current condominium",
)
def update_queue_settings(
    db: DbSession,
    admin_user: AdminUser,
    body: UpdateAdminQueueSettingsRequest,
) -> AdminQueueSettingsResponse:
    service = QueueService(db=db)
    return service.update_admin_settings(
        condominium_id=admin_user.condominium_id,
        queue_enabled=body.queue_enabled,
    )
