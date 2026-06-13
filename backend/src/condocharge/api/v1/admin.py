from __future__ import annotations

import csv
import io
import re
import secrets
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from condocharge.api.deps import AdminUser, DbSession
from condocharge.app.integrations.base.models import ConnectorStatus, StationTarget, StationVendor
from condocharge.app.integrations.legrand.driver import LegrandGreenUpDriver
from condocharge.app.services.email_service import EmailDeliveryError
from condocharge.app.services.resident_invitation_service import (
    InvitationError,
    ResidentInvitationService,
)
from condocharge.app.services.session_sync_service import SessionSyncService
from condocharge.core.config import get_settings
from condocharge.core.security import hash_password
from condocharge.models.charging import ChargingSession, ChargingStation, RfidUser
from condocharge.models.tenancy import AppUser, AppUserRole, ResidentInvitationToken
from condocharge.schemas.auth import (
    AppUserResponse,
    CondominiumResponse,
    CreateAppUserRequest,
    SyncSessionsRequest,
    SyncSessionsResponse,
)
from condocharge.schemas.consumption import (
    AdminCostReportResponse,
    AdminResidentRow,
    AdminRfidUserRow,
    AdminSettingsResponse,
    AssignRfidUserRequest,
    CostByResidentRow,
    CreateResidentRequest,
    CreateResidentResponse,
    InviteResidentRequest,
    InviteResidentResponse,
    ResidentCardResponse,
    UpdateAdminSettingsRequest,
    UpdateResidentRequest,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class PollStationsRequest(BaseModel):
    station_username: str = Field(min_length=1)
    station_password: str = Field(min_length=1)
    hosts: list[str] | None = None


class PolledStationResponse(BaseModel):
    station_id: int
    host: str
    observed_at: datetime
    availability: str
    connector_status: str | None = None
    computed_status: str


class PollStationsResponse(BaseModel):
    items: list[PolledStationResponse]
    errors: list[str] = Field(default_factory=list)


def _app_user_response(user: AppUser, condo_name: str) -> AppUserResponse:
    return AppUserResponse(
        id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        apartment_or_unit=user.apartment_or_unit,
        email=user.email,
        phone_number=user.phone_number,
        role=user.role,
        is_active=bool(user.is_active),
        must_change_password=bool(user.must_change_password),
        last_login_at=user.last_login_at,
        condominium=CondominiumResponse(id=user.condominium_id, name=condo_name),
    )


def _date_filters(*, from_date: datetime | None, to_date: datetime | None) -> list[object]:
    filters: list[object] = []
    if from_date is not None:
        filters.append(ChargingSession.start_time >= from_date)
    if to_date is not None:
        filters.append(ChargingSession.end_time <= to_date)
    return filters


def _validate_report_scope(
    db: DbSession,
    *,
    admin_user: AdminUser,
    resident_id: int | None,
    rfid_user_id: int | None,
) -> tuple[AppUser | None, RfidUser | None]:
    resident: AppUser | None = None
    if resident_id is not None:
        resident = db.get(AppUser, resident_id)
        if resident is None or resident.condominium_id != admin_user.condominium_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resident not found")

    rfid_user: RfidUser | None = None
    if rfid_user_id is not None:
        rfid_user = db.get(RfidUser, rfid_user_id)
        if rfid_user is None or rfid_user.condominium_id != admin_user.condominium_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RFID user not found")

    return resident, rfid_user


def _normalize_username_candidate(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", ".", value.strip().lower())
    normalized = re.sub(r"\.+", ".", normalized).strip(".-_")
    return normalized or "resident"


def _generate_resident_username(
    db: DbSession,
    *,
    condominium_id: int,
    email: str,
    first_name: str,
    last_name: str,
) -> str:
    local_part = email.split("@", 1)[0]
    base = _normalize_username_candidate(local_part)
    if not base or base == "resident":
        base = _normalize_username_candidate(f"{first_name}.{last_name}")

    candidate = base
    suffix = 2
    while db.scalar(
        select(AppUser.id)
        .where(AppUser.condominium_id == condominium_id)
        .where(AppUser.username == candidate)
        .limit(1)
    ):
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _resident_invitation_status(*, user: AppUser, latest_invitation: ResidentInvitationToken | None) -> tuple[str, datetime | None, datetime | None]:
    if user.is_active:
        return (
            "active",
            _as_utc(latest_invitation.created_at) if latest_invitation else None,
            _as_utc(latest_invitation.expires_at) if latest_invitation else None,
        )
    if latest_invitation is None:
        return "invitation_expired", None, None
    expires_at = _as_utc(latest_invitation.expires_at)
    created_at = _as_utc(latest_invitation.created_at)
    if latest_invitation.used_at is None and expires_at and expires_at > datetime.now(tz=UTC):
        return "invited", created_at, expires_at
    return "invitation_expired", created_at, expires_at


@router.get(
    "/users",
    response_model=list[AppUserResponse],
    summary="List application users (admin only)",
)
def list_app_users(db: DbSession, admin_user: AdminUser) -> list[AppUserResponse]:
    rows = db.scalars(
        select(AppUser)
        .where(AppUser.condominium_id == admin_user.condominium_id)
        .order_by(AppUser.username.asc())
    ).all()
    return [_app_user_response(user=u, condo_name=admin_user.condominium.name) for u in rows]


@router.post(
    "/users",
    response_model=AppUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create application user (admin only)",
)
def create_app_user(db: DbSession, body: CreateAppUserRequest, admin_user: AdminUser) -> AppUserResponse:
    existing = db.scalar(
        select(AppUser)
        .where(AppUser.condominium_id == admin_user.condominium_id)
        .where(AppUser.username == body.username)
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    user = AppUser(
        condominium_id=admin_user.condominium_id,
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=1 if body.is_active else 0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _app_user_response(user=user, condo_name=admin_user.condominium.name)


@router.get(
    "/residents",
    response_model=list[AdminResidentRow],
    summary="List condominium application users with linked RFID cards and consumption",
)
def list_residents(db: DbSession, admin_user: AdminUser) -> list[AdminResidentRow]:
    condo_id = admin_user.condominium_id
    price = float(admin_user.condominium.energy_price_eur_per_kwh)

    users = db.scalars(
        select(AppUser)
        .where(AppUser.condominium_id == condo_id)
        .order_by(AppUser.username.asc())
    ).all()
    user_ids = [user.id for user in users]

    cards_by_user: dict[int, list[ResidentCardResponse]] = {user.id: [] for user in users}
    card_rows = db.execute(
        select(RfidUser.id, RfidUser.rfid_id, RfidUser.name, RfidUser.app_user_id)
        .where(RfidUser.condominium_id == condo_id)
        .order_by(RfidUser.rfid_id.asc())
    ).all()
    for rfid_id, card_rfid, card_name, app_user_id in card_rows:
        if app_user_id is not None:
            cards_by_user.setdefault(int(app_user_id), []).append(
                ResidentCardResponse(id=int(rfid_id), rfid_id=str(card_rfid), name=card_name)
            )

    energy_by_user: dict[int, int] = {}
    energy_rows = db.execute(
        select(
            RfidUser.app_user_id,
            func.coalesce(func.sum(ChargingSession.energy_wh), 0),
        )
        .select_from(RfidUser)
        .outerjoin(ChargingSession, ChargingSession.rfid_user_id == RfidUser.id)
        .where(RfidUser.condominium_id == condo_id)
        .group_by(RfidUser.app_user_id)
    ).all()
    for app_user_id, energy_wh in energy_rows:
        if app_user_id is not None:
            energy_by_user[int(app_user_id)] = int(energy_wh or 0)

    latest_invitation_by_user: dict[int, ResidentInvitationToken] = {}
    if user_ids:
        invitation_rows = db.scalars(
            select(ResidentInvitationToken)
            .where(ResidentInvitationToken.app_user_id.in_(user_ids))
            .order_by(ResidentInvitationToken.created_at.desc(), ResidentInvitationToken.id.desc())
        ).all()
        for invitation in invitation_rows:
            latest_invitation_by_user.setdefault(invitation.app_user_id, invitation)

    result: list[AdminResidentRow] = []
    for user in users:
        total_energy_wh = energy_by_user.get(user.id, 0)
        total_energy_kwh = total_energy_wh / 1000.0
        invitation_status, invitation_sent_at, invitation_expires_at = _resident_invitation_status(
            user=user,
            latest_invitation=latest_invitation_by_user.get(user.id),
        )
        result.append(
            AdminResidentRow(
                app_user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                apartment_or_unit=user.apartment_or_unit,
                email=user.email,
                phone_number=user.phone_number,
                role=user.role,
                is_active=bool(user.is_active),
                must_change_password=bool(user.must_change_password),
                last_login_at=user.last_login_at,
                invitation_status=invitation_status,
                invitation_sent_at=invitation_sent_at,
                invitation_expires_at=invitation_expires_at,
                linked_cards=cards_by_user.get(user.id, []),
                total_energy_wh=total_energy_wh,
                total_energy_kwh=round(total_energy_kwh, 3),
                estimated_cost_eur=round(total_energy_kwh * price, 2),
            )
        )
    return result


@router.post(
    "/residents",
    response_model=CreateResidentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create resident user in current condominium",
)
def create_resident(db: DbSession, body: CreateResidentRequest, admin_user: AdminUser) -> CreateResidentResponse:
    username = _generate_resident_username(
        db,
        condominium_id=admin_user.condominium_id,
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
    )
    user = AppUser(
        condominium_id=admin_user.condominium_id,
        username=username,
        first_name=body.first_name,
        last_name=body.last_name,
        apartment_or_unit=body.apartment_or_unit,
        email=body.email,
        phone_number=body.phone_number,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        role=AppUserRole.RESIDENT,
        is_active=0,
        must_change_password=0,
    )
    db.add(user)
    db.flush()
    service = ResidentInvitationService(db=db, settings=get_settings())
    try:
        issue = service.issue_invitation(
            resident=user,
            condominium=admin_user.condominium,
            created_by_admin=admin_user,
            commit=False,
        )
    except InvitationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except EmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Invitation email failed: {exc}") from exc

    db.commit()
    db.refresh(user)
    return CreateResidentResponse(
        resident=_app_user_response(user=user, condo_name=admin_user.condominium.name),
        invitation_sent=True,
        invitation_expires_at=issue.expires_at,
    )


@router.post(
    "/residents/invite",
    response_model=InviteResidentResponse,
    summary="Send or resend a resident invitation email",
)
def invite_resident(
    db: DbSession,
    admin_user: AdminUser,
    body: InviteResidentRequest,
) -> InviteResidentResponse:
    user = db.get(AppUser, body.resident_id)
    if user is None or user.condominium_id != admin_user.condominium_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resident not found")
    if user.role != AppUserRole.RESIDENT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only residents can be invited here")

    service = ResidentInvitationService(db=db, settings=get_settings())
    try:
        issue = service.issue_invitation(
            resident=user,
            condominium=admin_user.condominium,
            created_by_admin=admin_user,
            commit=True,
        )
    except InvitationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except EmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Invitation email failed: {exc}") from exc

    return InviteResidentResponse(
        success=True,
        resident_id=user.id,
        invitation_expires_at=issue.expires_at,
    )


@router.patch(
    "/residents/{resident_id}",
    response_model=AppUserResponse,
    summary="Update resident profile fields in current condominium",
)
def update_resident(
    db: DbSession,
    admin_user: AdminUser,
    resident_id: int,
    body: UpdateResidentRequest,
) -> AppUserResponse:
    user = db.get(AppUser, resident_id)
    if user is None or user.condominium_id != admin_user.condominium_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resident not found")
    if user.role != AppUserRole.RESIDENT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only residents can be updated here")

    if "first_name" in body.model_fields_set:
        user.first_name = body.first_name
    if "last_name" in body.model_fields_set:
        user.last_name = body.last_name
    if "apartment_or_unit" in body.model_fields_set:
        user.apartment_or_unit = body.apartment_or_unit
    if "email" in body.model_fields_set:
        user.email = body.email
    if "phone_number" in body.model_fields_set:
        user.phone_number = body.phone_number
    if "is_active" in body.model_fields_set and body.is_active is not None:
        user.is_active = 1 if body.is_active else 0
    db.commit()
    db.refresh(user)
    return _app_user_response(user=user, condo_name=admin_user.condominium.name)


@router.post(
    "/residents/{resident_id}/force-password-change",
    response_model=AppUserResponse,
    summary="Force resident password change at next login",
)
def force_resident_password_change(
    db: DbSession,
    admin_user: AdminUser,
    resident_id: int,
) -> AppUserResponse:
    user = db.get(AppUser, resident_id)
    if user is None or user.condominium_id != admin_user.condominium_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resident not found")
    if user.role != AppUserRole.RESIDENT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only residents can be updated here")

    user.must_change_password = 1
    db.commit()
    db.refresh(user)
    return _app_user_response(user=user, condo_name=admin_user.condominium.name)


@router.get(
    "/rfid-users",
    response_model=list[AdminRfidUserRow],
    summary="List RFID users in the current condominium",
)
def list_rfid_users(db: DbSession, admin_user: AdminUser) -> list[AdminRfidUserRow]:
    rows = db.execute(
        select(RfidUser, AppUser.username)
        .select_from(RfidUser)
        .outerjoin(AppUser, AppUser.id == RfidUser.app_user_id)
        .where(RfidUser.condominium_id == admin_user.condominium_id)
        .order_by(RfidUser.rfid_id.asc())
    ).all()
    return [
        AdminRfidUserRow(
            id=rfid.id,
            rfid_id=rfid.rfid_id,
            name=rfid.name,
            app_user_id=rfid.app_user_id,
            assigned_username=username,
        )
        for rfid, username in rows
    ]


@router.get(
    "/settings",
    response_model=AdminSettingsResponse,
    summary="Get condominium admin settings",
)
def get_admin_settings(admin_user: AdminUser) -> AdminSettingsResponse:
    return AdminSettingsResponse(energy_price_eur_per_kwh=float(admin_user.condominium.energy_price_eur_per_kwh))


@router.patch(
    "/settings",
    response_model=AdminSettingsResponse,
    summary="Update condominium admin settings",
)
def update_admin_settings(
    db: DbSession,
    body: UpdateAdminSettingsRequest,
    admin_user: AdminUser,
) -> AdminSettingsResponse:
    admin_user.condominium.energy_price_eur_per_kwh = Decimal(str(body.energy_price_eur_per_kwh))
    db.commit()
    db.refresh(admin_user.condominium)
    return AdminSettingsResponse(energy_price_eur_per_kwh=float(admin_user.condominium.energy_price_eur_per_kwh))


@router.post(
    "/sync/sessions",
    response_model=SyncSessionsResponse,
    summary="Run Legrand session sync (admin only)",
)
def sync_sessions(db: DbSession, body: SyncSessionsRequest, admin_user: AdminUser) -> SyncSessionsResponse:
    hosts = body.hosts or ["192.168.1.200", "192.168.1.201"]
    driver = LegrandGreenUpDriver()
    try:
        service = SessionSyncService(db=db, driver=driver)
        result = service.sync_hosts(
            condominium_id=admin_user.condominium_id,
            hosts=hosts,
            username=body.station_username,
            password=body.station_password,
        )
    finally:
        driver.close()

    if result.errors:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"errors": result.errors})

    return SyncSessionsResponse(
        sessions_imported=result.sessions_imported,
        sessions_updated=result.sessions_updated,
        total_sessions=result.total_sessions,
        total_energy_imported_wh=result.total_energy_imported_wh,
    )


@router.post(
    "/poll/stations",
    response_model=PollStationsResponse,
    summary="Poll station status via vendor integration and update station status fields (admin only)",
)
def poll_stations(db: DbSession, body: PollStationsRequest, admin_user: AdminUser) -> PollStationsResponse:
    stations = db.scalars(
        select(ChargingStation)
        .where(ChargingStation.condominium_id == admin_user.condominium_id)
        .order_by(ChargingStation.id.asc())
    ).all()
    hosts = [h.strip() for h in (body.hosts or [s.host for s in stations]) if h and h.strip()]
    host_to_station = {s.host: s for s in stations}

    driver = LegrandGreenUpDriver()
    try:
        items: list[PolledStationResponse] = []
        errors: list[str] = []
        for host in hosts:
            station = host_to_station.get(host)
            if station is None:
                errors.append(f"{host}: unknown station host")
                continue
            try:
                driver.login(host, body.station_username, body.station_password)
                snapshot = driver.get_status(
                    StationTarget(
                        station_id=str(station.id),
                        name=station.name or f"Station #{station.id}",
                        vendor=StationVendor.LEGRAND_GREENUP,
                        host=host,
                    )
                )
                observed_at = snapshot.observed_at
                connector = snapshot.connectors[0].status if snapshot.connectors else ConnectorStatus.UNKNOWN
                if snapshot.availability == "offline":
                    computed = "offline"
                elif connector == ConnectorStatus.CHARGING:
                    computed = "charging"
                elif connector == ConnectorStatus.OCCUPIED:
                    computed = "occupied"
                elif connector == ConnectorStatus.AVAILABLE:
                    computed = "available"
                else:
                    computed = "online"

                station.status = computed
                station.status_source = "polling"
                station.last_sync_at = observed_at
                station.active_session = computed == "charging"
                station.active_session_source = "polling"
                items.append(
                    PolledStationResponse(
                        station_id=station.id,
                        host=host,
                        observed_at=observed_at,
                        availability=str(snapshot.availability),
                        connector_status=str(connector),
                        computed_status=computed,
                    )
                )
            except Exception as exc:
                station.status = "offline"
                station.status_source = "polling"
                station.last_sync_at = datetime.now(tz=UTC)
                station.active_session = False
                station.active_session_source = "polling"
                errors.append(f"{host}: {type(exc).__name__}: {exc}")

        db.commit()
        return PollStationsResponse(items=items, errors=errors)
    finally:
        driver.close()


@router.post(
    "/rfid-users/{rfid_user_id}/assign",
    summary="Assign an RFID user to a resident (admin only)",
)
def assign_rfid_user(
    db: DbSession,
    admin_user: AdminUser,
    rfid_user_id: int,
    body: AssignRfidUserRequest,
) -> None:
    rfid = db.get(RfidUser, rfid_user_id)
    if rfid is None or rfid.condominium_id != admin_user.condominium_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RFID user not found")

    if body.app_user_id is None:
        rfid.app_user_id = None
        db.commit()
        return None

    user = db.get(AppUser, body.app_user_id)
    if user is None or user.condominium_id != admin_user.condominium_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.role != AppUserRole.RESIDENT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="RFID users can only be assigned to residents")

    rfid.app_user_id = user.id
    db.commit()
    return None


@router.get(
    "/reports/costs",
    response_model=AdminCostReportResponse,
    summary="Get condominium cost report (admin only)",
)
def admin_cost_report(
    db: DbSession,
    admin_user: AdminUser,
    resident_id: Annotated[int | None, Query()] = None,
    rfid_user_id: Annotated[int | None, Query()] = None,
    from_date: Annotated[datetime | None, Query()] = None,
    to_date: Annotated[datetime | None, Query()] = None,
) -> AdminCostReportResponse:
    _validate_report_scope(db, admin_user=admin_user, resident_id=resident_id, rfid_user_id=rfid_user_id)

    condo_id = admin_user.condominium_id
    price = float(admin_user.condominium.energy_price_eur_per_kwh)
    filters = _date_filters(from_date=from_date, to_date=to_date)

    totals_row = db.execute(
        select(
            func.count(ChargingSession.id),
            func.coalesce(func.sum(ChargingSession.energy_wh), 0),
        )
        .select_from(ChargingSession)
        .outerjoin(RfidUser, RfidUser.id == ChargingSession.rfid_user_id)
        .where(ChargingSession.condominium_id == condo_id)
        .where(*filters)
        .where(RfidUser.app_user_id == resident_id if resident_id is not None else True)
        .where(RfidUser.id == rfid_user_id if rfid_user_id is not None else True)
    ).one()

    total_sessions = int(totals_row[0] or 0)
    total_energy_wh = int(totals_row[1] or 0)
    total_energy_kwh = total_energy_wh / 1000.0
    total_cost = round(total_energy_kwh * price, 2)

    rows = db.execute(
        select(
            AppUser.id,
            AppUser.username,
            func.count(ChargingSession.id),
            func.coalesce(func.sum(ChargingSession.energy_wh), 0),
            func.count(func.distinct(RfidUser.id)),
        )
        .select_from(RfidUser)
        .join(ChargingSession, ChargingSession.rfid_user_id == RfidUser.id)
        .outerjoin(AppUser, AppUser.id == RfidUser.app_user_id)
        .where(RfidUser.condominium_id == condo_id)
        .where(ChargingSession.condominium_id == condo_id)
        .where(*filters)
        .where(AppUser.id == resident_id if resident_id is not None else True)
        .where(RfidUser.id == rfid_user_id if rfid_user_id is not None else True)
        .group_by(AppUser.id, AppUser.username)
        .order_by(func.coalesce(func.sum(ChargingSession.energy_wh), 0).desc(), AppUser.username.asc())
    ).all()

    by_resident: list[CostByResidentRow] = []
    for app_user_id, username, sessions_count, energy_wh, rfid_count in rows:
        energy_wh_i = int(energy_wh or 0)
        energy_kwh = energy_wh_i / 1000.0
        by_resident.append(
            CostByResidentRow(
                app_user_id=int(app_user_id) if app_user_id is not None else None,
                resident=str(username) if username is not None else "Unassigned",
                sessions_count=int(sessions_count or 0),
                energy_wh=energy_wh_i,
                energy_kwh=round(energy_kwh, 3),
                estimated_cost_eur=round(energy_kwh * price, 2),
                rfid_count=int(rfid_count or 0),
            )
        )

    return AdminCostReportResponse(
        from_date=from_date,
        to_date=to_date,
        resident_id=resident_id,
        rfid_user_id=rfid_user_id,
        total_sessions=total_sessions,
        total_energy_wh=total_energy_wh,
        total_energy_kwh=round(total_energy_kwh, 3),
        energy_price_eur_per_kwh=price,
        total_estimated_cost_eur=total_cost,
        by_resident=by_resident,
    )


@router.get(
    "/reports/costs/export.csv",
    summary="Export condominium cost report as CSV (admin only)",
)
def admin_cost_report_csv(
    db: DbSession,
    admin_user: AdminUser,
    resident_id: Annotated[int | None, Query()] = None,
    rfid_user_id: Annotated[int | None, Query()] = None,
    from_date: Annotated[datetime | None, Query()] = None,
    to_date: Annotated[datetime | None, Query()] = None,
) -> Response:
    _validate_report_scope(db, admin_user=admin_user, resident_id=resident_id, rfid_user_id=rfid_user_id)

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "resident",
            "rfid",
            "sessions_count",
            "energy_kwh",
            "estimated_cost_eur",
            "from_date",
            "to_date",
        ],
    )
    writer.writeheader()

    condo_id = admin_user.condominium_id
    price = float(admin_user.condominium.energy_price_eur_per_kwh)
    filters = _date_filters(from_date=from_date, to_date=to_date)
    rows = db.execute(
        select(
            AppUser.username,
            RfidUser.rfid_id,
            func.count(ChargingSession.id),
            func.coalesce(func.sum(ChargingSession.energy_wh), 0),
        )
        .select_from(RfidUser)
        .join(ChargingSession, ChargingSession.rfid_user_id == RfidUser.id)
        .outerjoin(AppUser, AppUser.id == RfidUser.app_user_id)
        .where(RfidUser.condominium_id == condo_id)
        .where(ChargingSession.condominium_id == condo_id)
        .where(*filters)
        .where(AppUser.id == resident_id if resident_id is not None else True)
        .where(RfidUser.id == rfid_user_id if rfid_user_id is not None else True)
        .group_by(AppUser.username, RfidUser.rfid_id)
        .order_by(func.coalesce(func.sum(ChargingSession.energy_wh), 0).desc(), RfidUser.rfid_id.asc())
    ).all()

    for username, rfid_id, sessions_count, energy_wh in rows:
        energy_wh_i = int(energy_wh or 0)
        energy_kwh = energy_wh_i / 1000.0
        writer.writerow(
            {
                "resident": str(username) if username is not None else "Unassigned",
                "rfid": str(rfid_id),
                "sessions_count": int(sessions_count or 0),
                "energy_kwh": f"{energy_kwh:.3f}",
                "estimated_cost_eur": f"{energy_kwh * price:.2f}",
                "from_date": from_date.isoformat() if from_date else "",
                "to_date": to_date.isoformat() if to_date else "",
            }
        )

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=condocharge_cost_report.csv"},
    )
