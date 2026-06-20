from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from condocharge.api.deps import CurrentUser, DbSession
from condocharge.app.services.queue_service import QueueDisabledError, QueueService
from condocharge.models.tenancy import AppUserRole
from condocharge.schemas.queue import ResidentQueueStatusResponse

router = APIRouter(prefix="/resident/queue", tags=["resident-queue"])


def _require_resident(current_user: CurrentUser) -> None:
    if current_user.role != AppUserRole.RESIDENT.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@router.get(
    "",
    response_model=ResidentQueueStatusResponse,
    summary="Get the current resident queue status",
)
def get_queue_status(db: DbSession, current_user: CurrentUser) -> ResidentQueueStatusResponse:
    _require_resident(current_user)
    service = QueueService(db=db)
    return service.get_resident_status(resident=current_user)


@router.post(
    "",
    response_model=ResidentQueueStatusResponse,
    summary="Join the condominium charging queue",
)
def join_queue(db: DbSession, current_user: CurrentUser) -> ResidentQueueStatusResponse:
    _require_resident(current_user)
    service = QueueService(db=db)
    try:
        return service.join_queue(resident=current_user)
    except QueueDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete(
    "",
    response_model=ResidentQueueStatusResponse,
    summary="Leave the condominium charging queue",
)
def leave_queue(db: DbSession, current_user: CurrentUser) -> ResidentQueueStatusResponse:
    _require_resident(current_user)
    service = QueueService(db=db)
    return service.leave_queue(resident=current_user)
