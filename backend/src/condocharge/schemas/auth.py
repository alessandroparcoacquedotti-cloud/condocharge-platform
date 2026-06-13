from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CondominiumResponse(BaseModel):
    id: int
    name: str


class AppUserResponse(BaseModel):
    id: int
    username: str
    first_name: str | None = None
    last_name: str | None = None
    apartment_or_unit: str | None = None
    email: str | None = None
    phone_number: str | None = None
    role: str
    is_active: bool
    must_change_password: bool = False
    last_login_at: datetime | None = None
    condominium: CondominiumResponse


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    condominium: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginResponse(BaseModel):
    token: TokenResponse
    user: AppUserResponse


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class InvitationStatusResponse(BaseModel):
    valid: bool
    username: str | None = None
    condominium_name: str | None = None
    expires_at: datetime | None = None


class InvitationCompleteRequest(BaseModel):
    password: str = Field(min_length=8)


class InvitationCompleteResponse(BaseModel):
    success: bool
    username: str


class CreateAppUserRequest(BaseModel):
    username: str = Field(min_length=1)
    email: str | None = None
    password: str = Field(min_length=8)
    role: str
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not EMAIL_RE.match(value):
            raise ValueError("Invalid email format")
        return value


class SyncSessionsRequest(BaseModel):
    hosts: list[str] = Field(default_factory=list)
    station_username: str = Field(min_length=1)
    station_password: str = Field(min_length=1)


class SyncSessionsResponse(BaseModel):
    sessions_imported: int
    sessions_updated: int
    total_sessions: int
    total_energy_imported_wh: int
