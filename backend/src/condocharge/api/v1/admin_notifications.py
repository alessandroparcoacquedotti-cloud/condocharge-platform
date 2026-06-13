from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from condocharge.api.deps import AdminUser, DbSession
from condocharge.api.v1._helpers import paginate
from condocharge.models.tenancy import ResidentEmailNotification
from condocharge.schemas.notifications import AdminNotificationLogListResponse, AdminNotificationLogRow


router = APIRouter(prefix="/admin/notifications", tags=["admin-notifications"])


@router.get(
    "/logs",
    response_model=AdminNotificationLogListResponse,
    summary="List resident email notification logs (admin only)",
)
def list_notification_logs(
    db: DbSession,
    admin_user: AdminUser,
    notification_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    resident_app_user_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AdminNotificationLogListResponse:
    filters = [ResidentEmailNotification.condominium_id == admin_user.condominium_id]
    if notification_type:
        filters.append(ResidentEmailNotification.notification_type == notification_type)
    if status:
        filters.append(ResidentEmailNotification.status == status)
    if resident_app_user_id is not None:
        filters.append(ResidentEmailNotification.resident_app_user_id == resident_app_user_id)

    base_count_from = select(ResidentEmailNotification.id).where(*filters)
    query = (
        select(ResidentEmailNotification)
        .options(joinedload(ResidentEmailNotification.resident))
        .where(*filters)
        .order_by(ResidentEmailNotification.created_at.desc(), ResidentEmailNotification.id.desc())
    )
    rows, pagination = paginate(db, base_count_from=base_count_from, query=query, limit=limit, offset=offset)

    items: list[AdminNotificationLogRow] = []
    for n in rows:
        resident = n.resident
        resident_username = resident.username if resident is not None else "-"
        resident_email = resident.email if resident is not None else None
        items.append(
            AdminNotificationLogRow(
                id=n.id,
                created_at=n.created_at,
                sent_at=n.sent_at,
                condominium_id=n.condominium_id,
                resident_app_user_id=n.resident_app_user_id,
                resident_username=resident_username,
                resident_email=resident_email,
                notification_type=n.notification_type,
                dedupe_key=n.dedupe_key,
                status=n.status,
                error_message=n.error_message,
            )
        )

    return AdminNotificationLogListResponse(items=items, pagination=pagination)
