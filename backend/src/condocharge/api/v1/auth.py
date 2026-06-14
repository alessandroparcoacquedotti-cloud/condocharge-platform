from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from condocharge.api.deps import CurrentUser, DbSession
from condocharge.app.services.resident_invitation_service import (
    InvitationError,
    ResidentInvitationService,
)
from condocharge.core.config import get_settings
from condocharge.core.rate_limit import (
    RateLimitRule,
    client_identifier_from_request,
    enforce_rate_limit,
    fingerprint_value,
)
from condocharge.core.security import create_access_token, hash_password, verify_password
from condocharge.models.tenancy import AppUser, Condominium
from condocharge.schemas.auth import (
    AppUserResponse,
    ChangePasswordRequest,
    CondominiumResponse,
    InvitationCompleteRequest,
    InvitationCompleteResponse,
    InvitationStatusResponse,
    LoginRequest,
    LoginResponse,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_IP_RULE = RateLimitRule(limit=10, window_seconds=300)
_LOGIN_USER_RULE = RateLimitRule(limit=5, window_seconds=300)
_INVITATION_STATUS_RULE = RateLimitRule(limit=30, window_seconds=300)
_INVITATION_COMPLETE_IP_RULE = RateLimitRule(limit=10, window_seconds=900)
_INVITATION_COMPLETE_TOKEN_RULE = RateLimitRule(limit=5, window_seconds=900)


def _user_to_response(user: AppUser, condo: Condominium) -> AppUserResponse:
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
        condominium=CondominiumResponse(id=condo.id, name=condo.name),
    )


def _request_fingerprint(request: Request) -> str:
    return fingerprint_value(client_identifier_from_request(request))


def _enforce_login_rate_limits(*, request: Request, username: str) -> None:
    request_id = _request_fingerprint(request)
    username_key = fingerprint_value(username)
    enforce_rate_limit(
        bucket=f"auth:login:ip:{request_id}",
        rule=_LOGIN_IP_RULE,
        detail="Too many login attempts. Please try again later.",
    )
    enforce_rate_limit(
        bucket=f"auth:login:user:{request_id}:{username_key}",
        rule=_LOGIN_USER_RULE,
        detail="Too many login attempts for this account. Please try again later.",
    )


def _enforce_invitation_status_rate_limit(*, request: Request) -> None:
    enforce_rate_limit(
        bucket=f"auth:invitation:status:{_request_fingerprint(request)}",
        rule=_INVITATION_STATUS_RULE,
        detail="Too many invitation checks. Please try again later.",
    )


def _enforce_invitation_completion_rate_limits(*, request: Request, token: str) -> None:
    request_id = _request_fingerprint(request)
    token_key = fingerprint_value(token)
    enforce_rate_limit(
        bucket=f"auth:invitation:complete:ip:{request_id}",
        rule=_INVITATION_COMPLETE_IP_RULE,
        detail="Too many invitation completion attempts. Please try again later.",
    )
    enforce_rate_limit(
        bucket=f"auth:invitation:complete:token:{request_id}:{token_key}",
        rule=_INVITATION_COMPLETE_TOKEN_RULE,
        detail="Too many invitation completion attempts for this link. Please try again later.",
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login and obtain JWT access token",
)
def login(request: Request, db: DbSession, body: LoginRequest) -> LoginResponse:
    _enforce_login_rate_limits(request=request, username=body.username)
    if body.condominium:
        requested_condo = body.condominium.strip()
        normalized_condo = requested_condo.lower()
        row = db.execute(
            select(AppUser, Condominium)
            .join(Condominium, Condominium.id == AppUser.condominium_id)
            .where(Condominium.is_active == 1)
            .where(AppUser.is_active == 1)
            .where(func.lower(func.trim(Condominium.name)) == normalized_condo)
            .where(AppUser.username == body.username)
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        user, condo = row
    else:
        rows = db.execute(
            select(AppUser, Condominium)
            .join(Condominium, Condominium.id == AppUser.condominium_id)
            .where(AppUser.username == body.username)
            .where(AppUser.is_active == 1)
            .where(Condominium.is_active == 1)
        ).all()
        if not rows:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if len(rows) > 1:
            condo_names = sorted({c.name for _, c in rows})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Multiple active condominiums found for this username. Specify condominium. Options: {', '.join(condo_names)}",
            )
        user, condo = rows[0]

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    settings = get_settings()
    token = create_access_token(
        user_id=user.id,
        condominium_id=user.condominium_id,
        role=user.role,
        token_version=int(getattr(user, "token_version", 0) or 0),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.jwt_access_token_expires_minutes,
    )

    user.last_login_at = datetime.now(tz=UTC)
    try:
        db.commit()
    except Exception:
        db.rollback()
        logging.getLogger("uvicorn.error").warning(
            "Failed to update last_login_at user_id=%s condominium_id=%s",
            user.id,
            user.condominium_id,
            exc_info=True,
        )
    return LoginResponse(
        token=TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=settings.jwt_access_token_expires_minutes * 60,
        ),
        user=_user_to_response(user, condo),
    )


@router.post(
    "/change-password",
    response_model=AppUserResponse,
    summary="Change password for current user",
)
def change_password(db: DbSession, current_user: CurrentUser, body: ChangePasswordRequest) -> AppUserResponse:
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    current_user.password_hash = hash_password(body.new_password)
    current_user.must_change_password = 0
    current_user.token_version = int(getattr(current_user, "token_version", 0) or 0) + 1
    db.commit()
    db.refresh(current_user)

    condo = db.get(Condominium, current_user.condominium_id)
    if condo is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    return _user_to_response(current_user, condo)


@router.get(
    "/me",
    response_model=AppUserResponse,
    summary="Get current authenticated user",
)
def me(db: DbSession, current_user: CurrentUser) -> AppUserResponse:
    condo = db.get(Condominium, current_user.condominium_id)
    if condo is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    return _user_to_response(current_user, condo)


@router.get(
    "/invitation/{token}",
    response_model=InvitationStatusResponse,
    summary="Validate a resident invitation token",
)
def get_invitation_status(request: Request, db: DbSession, token: str) -> InvitationStatusResponse:
    _enforce_invitation_status_rate_limit(request=request)
    lookup = ResidentInvitationService(db=db, settings=get_settings()).get_invitation(token=token)
    return InvitationStatusResponse(
        valid=lookup.valid,
        username=lookup.username,
        condominium_name=lookup.condominium_name,
        expires_at=lookup.expires_at,
    )


@router.post(
    "/invitation/{token}/complete",
    response_model=InvitationCompleteResponse,
    summary="Complete a resident invitation by setting the password",
)
def complete_invitation(
    request: Request,
    db: DbSession,
    token: str,
    body: InvitationCompleteRequest,
) -> InvitationCompleteResponse:
    _enforce_invitation_completion_rate_limits(request=request, token=token)
    service = ResidentInvitationService(db=db, settings=get_settings())
    try:
        lookup = service.complete_invitation(token=token, password=body.password)
    except InvitationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return InvitationCompleteResponse(success=True, username=lookup.username or "")
