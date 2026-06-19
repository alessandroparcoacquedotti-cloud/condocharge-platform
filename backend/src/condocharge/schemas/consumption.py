from __future__ import annotations

import re
from datetime import datetime
from typing import cast

from pydantic import BaseModel, Field, field_validator

from condocharge.schemas.api import ResidentSessionResponse
from condocharge.schemas.auth import AppUserResponse
from condocharge.schemas.telegram import TelegramLinkStatusResponse


class ResidentCardResponse(BaseModel):
    id: int
    rfid_id: str
    name: str | None = None


class ResidentSummaryResponse(BaseModel):
    from_date: datetime | None = None
    to_date: datetime | None = None
    total_sessions: int
    total_energy_wh: int
    total_energy_kwh: float
    energy_price_eur_per_kwh: float
    estimated_cost_eur: float
    estimated_annual_cost_eur: float
    latest_session: ResidentSessionResponse | None = None
    cards: list[ResidentCardResponse]
    monthly_breakdown: list[MonthlyConsumptionPoint]


class MonthlyConsumptionPoint(BaseModel):
    month: str
    total_energy_wh: int
    total_energy_kwh: float
    estimated_cost_eur: float


class CostByResidentRow(BaseModel):
    app_user_id: int | None = None
    resident: str
    sessions_count: int
    energy_wh: int
    energy_kwh: float
    estimated_cost_eur: float
    rfid_count: int


class AdminCostReportResponse(BaseModel):
    from_date: datetime | None = None
    to_date: datetime | None = None
    resident_id: int | None = None
    rfid_user_id: int | None = None
    total_sessions: int
    total_energy_wh: int
    total_energy_kwh: float
    energy_price_eur_per_kwh: float
    total_estimated_cost_eur: float
    by_resident: list[CostByResidentRow]


class AssignRfidUserRequest(BaseModel):
    app_user_id: int | None = None


class CreateResidentRequest(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    apartment_or_unit: str = Field(min_length=1)
    email: str
    phone_number: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
            raise ValueError("Invalid email format")
        return value


class CreateResidentResponse(BaseModel):
    resident: AppUserResponse
    invitation_sent: bool
    invitation_expires_at: datetime


class InviteResidentRequest(BaseModel):
    resident_id: int = Field(ge=1)


class InviteResidentResponse(BaseModel):
    success: bool
    resident_id: int
    invitation_expires_at: datetime


class AdminResidentRow(BaseModel):
    app_user_id: int
    username: str
    first_name: str | None = None
    last_name: str | None = None
    apartment_or_unit: str | None = None
    email: str | None = None
    phone_number: str | None = None
    role: str
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None = None
    invitation_status: str
    invitation_sent_at: datetime | None = None
    invitation_expires_at: datetime | None = None
    linked_cards: list[ResidentCardResponse]
    total_energy_wh: int
    total_energy_kwh: float
    estimated_cost_eur: float


class AdminRfidUserRow(BaseModel):
    id: int
    rfid_id: str
    name: str | None = None
    app_user_id: int | None = None
    assigned_username: str | None = None


class AdminSettingsResponse(BaseModel):
    energy_price_eur_per_kwh: float
    telegram_station_available_enabled: bool
    telegram_charging_completed_enabled: bool
    telegram_agent_offline_enabled: bool
    telegram_agent_recovered_enabled: bool


class UpdateAdminSettingsRequest(BaseModel):
    energy_price_eur_per_kwh: float = Field(ge=0)
    telegram_station_available_enabled: bool = True
    telegram_charging_completed_enabled: bool = True
    telegram_agent_offline_enabled: bool = True
    telegram_agent_recovered_enabled: bool = True


class UpdateResidentRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    apartment_or_unit: str | None = None
    email: str | None = None
    phone_number: str | None = None
    is_active: bool | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        email = cast(str, value)
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise ValueError("Invalid email format")
        return email


class ResidentNotificationPreferencesResponse(BaseModel):
    charging_completed: bool
    station_available: bool
    station_back_online: bool
    agent_offline: bool
    agent_recovered: bool


class ResidentNotificationPreferencesUpdateRequest(BaseModel):
    charging_completed: bool
    station_available: bool
    station_back_online: bool
    agent_offline: bool
    agent_recovered: bool


class ResidentProfileResponse(BaseModel):
    username: str
    first_name: str | None = None
    last_name: str | None = None
    apartment_or_unit: str | None = None
    email: str | None = None
    phone_number: str | None = None
    linked_cards: list[ResidentCardResponse]
    notification_preferences: ResidentNotificationPreferencesResponse
    telegram: TelegramLinkStatusResponse


class UpdateResidentProfileRequest(BaseModel):
    email: str | None = None
    phone_number: str | None = None

    @field_validator("email")
    @classmethod
    def validate_profile_email(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        email = cast(str, value)
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise ValueError("Invalid email format")
        return email
