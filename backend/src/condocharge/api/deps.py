from __future__ import annotations

from typing import Annotated

import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from condocharge.core.config import get_settings
from condocharge.core.security import decode_access_token
from condocharge.db.session import get_db_session
from condocharge.models.tenancy import AppUser, AppUserRole

DbSession = Annotated[Session, Depends(get_db_session)]

_bearer = HTTPBearer(auto_error=False)
BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)]

_agent_bearer = HTTPBearer(auto_error=False)
AgentBearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Security(_agent_bearer)]


@dataclass(frozen=True)
class AgentPrincipal:
    agent_id: str
    condominium_id: int


def get_current_agent(request: Request, credentials: AgentBearerCredentials) -> AgentPrincipal:
    settings = get_settings()
    if not settings.agent_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent disabled")

    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    token = credentials.credentials.strip()
    expected_current = settings.agent_token_current.strip()
    expected_next = settings.agent_token_next.strip()
    if not expected_current:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token")

    if not secrets.compare_digest(token, expected_current) and not (
        expected_next and secrets.compare_digest(token, expected_next)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token")

    agent_id = (request.headers.get("X-CondoCharge-Agent-Id") or "").strip()
    if not agent_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing agent id")

    raw_condo = (request.headers.get("X-CondoCharge-Condominium-Id") or "").strip()
    try:
        condominium_id = int(raw_condo)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid condominium id") from None

    allowed = settings.agent_allowed_condominium_id_set
    if not allowed or condominium_id not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    return AgentPrincipal(agent_id=agent_id, condominium_id=condominium_id)


CurrentAgent = Annotated[AgentPrincipal, Depends(get_current_agent)]


def get_current_user(
    db: DbSession,
    request: Request,
    credentials: BearerCredentials,
) -> AppUser:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    settings = get_settings()
    try:
        payload = decode_access_token(
            token=credentials.credentials,
            secret_key=settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from None

    user = db.get(AppUser, int(payload.sub))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    if user.condominium_id != payload.condominium_id or user.role != payload.role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if int(getattr(user, "token_version", 0) or 0) != payload.ver:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if user.role == AppUserRole.RESIDENT and bool(getattr(user, "must_change_password", 0)):
        path = request.url.path
        if path.startswith("/api/v1/admin"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        if path not in ("/api/v1/auth/me", "/api/v1/auth/change-password"):
            raise HTTPException(status_code=428, detail="Password change required")
    return user


CurrentUser = Annotated[AppUser, Depends(get_current_user)]


def require_admin(current_user: CurrentUser) -> AppUser:
    if current_user.role != AppUserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return current_user


AdminUser = Annotated[AppUser, Depends(require_admin)]


def require_non_resident(current_user: CurrentUser) -> AppUser:
    if current_user.role == AppUserRole.RESIDENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return current_user


NonResidentUser = Annotated[AppUser, Depends(require_non_resident)]
