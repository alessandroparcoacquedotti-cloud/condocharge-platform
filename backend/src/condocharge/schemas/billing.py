from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from condocharge.schemas.api import SessionResponse
from condocharge.schemas.auth import EMAIL_RE


class CreateBillingPeriodRequest(BaseModel):
    name: str = Field(min_length=1)
    period_start: datetime
    period_end: datetime


class UpdateStatementPaymentStatusRequest(BaseModel):
    payment_status: str
    note: str | None = None


class BillingPaymentEventResponse(BaseModel):
    id: int
    changed_by_app_user_id: int
    changed_by_username: str
    old_status: str
    new_status: str
    note: str | None = None
    created_at: datetime


class BillingStatementResponse(BaseModel):
    id: int
    billing_period_id: int
    period_name: str
    resident_app_user_id: int
    resident_username: str
    statement_number: str
    payment_reference: str
    sessions_count: int
    energy_kwh: float
    amount_eur: float
    amount_paid_eur: float
    amount_due_eur: float
    payment_status: str
    generated_at: datetime
    paid_at: datetime | None = None
    last_reminder_at: datetime | None = None
    reminder_count: int


class BillingPaymentResponse(BaseModel):
    id: int
    statement_id: int
    amount_eur: float
    method: str
    transaction_reference: str | None = None
    note: str | None = None
    received_at: datetime
    created_by_app_user_id: int
    created_by_username: str
    created_at: datetime


class BillingEmailNotificationResponse(BaseModel):
    id: int
    statement_id: int
    recipient_email: str
    notification_type: str
    subject: str
    body_preview: str
    status: str
    error_message: str | None = None
    sent_at: datetime | None = None
    retry_of_notification_id: int | None = None
    created_by_app_user_id: int
    created_by_username: str
    created_at: datetime


class EmailAttachmentResponse(BaseModel):
    filename: str
    content_type: str
    size_bytes: int


class BillingUnmatchedPaymentResponse(BaseModel):
    id: int
    condominium_id: int
    raw_reference: str | None = None
    amount_eur: float
    received_at: datetime
    transaction_reference: str | None = None
    method: str | None = None
    note: str | None = None
    status: str
    matched_statement_id: int | None = None
    created_at: datetime


class CreateBillingPaymentRequest(BaseModel):
    amount_eur: float = Field(gt=0)
    method: str
    transaction_reference: str | None = None
    note: str | None = None
    received_at: datetime


class WaiveStatementRequest(BaseModel):
    note: str | None = None


class ReminderPayloadResponse(BaseModel):
    to: str
    resident_username: str
    statement_number: str
    subject: str
    body_preview: str
    html_preview: str
    amount_due_eur: float
    payment_reference: str
    period: str
    email_enabled: bool
    delivery_status: str
    notification_id: int
    attachments: list[EmailAttachmentResponse] = Field(default_factory=list)


class ReceiptPayloadResponse(BaseModel):
    to: str
    resident_username: str
    statement_number: str
    subject: str
    body_preview: str
    html_preview: str
    amount_eur: float
    amount_paid_eur: float
    payment_reference: str
    payment_date: datetime | None = None
    email_enabled: bool
    delivery_status: str
    notification_id: int
    attachments: list[EmailAttachmentResponse] = Field(default_factory=list)


class StatementPayloadResponse(BaseModel):
    to: str
    resident_username: str
    statement_number: str
    subject: str
    body_preview: str
    html_preview: str
    amount_eur: float
    amount_due_eur: float
    payment_reference: str
    period: str
    email_enabled: bool
    delivery_status: str
    notification_id: int
    attachments: list[EmailAttachmentResponse] = Field(default_factory=list)


class MatchUnmatchedPaymentRequest(BaseModel):
    statement_id: int


class IgnoreUnmatchedPaymentRequest(BaseModel):
    note: str | None = None


class BillingStatementDetailResponse(BillingStatementResponse):
    period_start: datetime
    period_end: datetime
    energy_price_eur_per_kwh_snapshot: float
    sessions: list[SessionResponse]
    payment_history: list[BillingPaymentEventResponse]
    payments: list[BillingPaymentResponse]
    notifications: list[BillingEmailNotificationResponse] = Field(default_factory=list)


class BillingPeriodResponse(BaseModel):
    id: int
    condominium_id: int
    name: str
    period_start: datetime
    period_end: datetime
    status: str
    energy_price_eur_per_kwh_snapshot: float
    created_at: datetime
    closed_at: datetime | None = None
    statements_count: int
    statements_total_amount_eur: float
    unassigned_sessions_count: int
    unassigned_energy_kwh: float
    unassigned_amount_eur: float


class BillingPeriodDetailResponse(BillingPeriodResponse):
    statements: list[BillingStatementResponse]


class SettlementSummaryResponse(BaseModel):
    total_billed_eur: float
    paid_eur: float
    unpaid_eur: float
    waived_eur: float
    partially_paid_eur: float
    collection_rate: float
    open_periods: int
    closed_periods: int


class ReconciliationRow(BaseModel):
    statement_id: int
    statement_number: str
    payment_reference: str
    billing_period_id: int
    period_name: str
    resident_app_user_id: int
    resident_username: str
    amount_eur: float
    amount_paid_eur: float
    amount_due_eur: float
    payment_status: str
    last_payment_at: datetime | None = None
    reminder_count: int
    last_reminder_at: datetime | None = None


class ReconciliationResponse(BaseModel):
    rows: list[ReconciliationRow]
    total_amount_eur: float
    total_paid_eur: float
    total_due_eur: float
    total_received_eur: float
    unmatched_payments_count: int
    unmatched_payments_amount_eur: float
    unmatched_payments: list[BillingUnmatchedPaymentResponse]


class BillingPaymentImportRowResponse(BaseModel):
    id: int
    import_job_id: int
    row_number: int
    raw_payment_reference: str | None = None
    raw_statement_number: str | None = None
    amount_eur: float | None = None
    received_at: datetime | None = None
    transaction_reference: str | None = None
    method: str | None = None
    status: str
    matched_statement_id: int | None = None
    unmatched_payment_id: int | None = None
    error_message: str | None = None
    created_at: datetime


class BillingPaymentImportJobSummaryResponse(BaseModel):
    id: int
    condominium_id: int
    filename: str
    status: str
    rows_total: int
    rows_processed: int
    progress_percent: int
    rows_matched: int
    rows_unmatched: int
    rows_duplicate: int
    rows_failed: int
    error_message: str | None = None
    created_by_app_user_id: int
    created_by_username: str
    created_at: datetime
    completed_at: datetime | None = None


class BillingPaymentImportJobDetailResponse(BillingPaymentImportJobSummaryResponse):
    rows: list[BillingPaymentImportRowResponse] = Field(default_factory=list)


class BillingReminderRuleResponse(BaseModel):
    id: int
    condominium_id: int
    enabled: bool
    days_after_period_close: int
    repeat_every_days: int
    max_reminders: int
    min_amount_due_eur: float
    created_at: datetime
    updated_at: datetime


class UpdateBillingReminderRuleRequest(BaseModel):
    enabled: bool
    days_after_period_close: int = Field(ge=0)
    repeat_every_days: int = Field(ge=1)
    max_reminders: int = Field(ge=0)
    min_amount_due_eur: float = Field(ge=0)


class ReminderRunResponse(BaseModel):
    candidates_count: int
    sent_count: int
    preview_count: int
    skipped_count: int
    failed_count: int


class PaymentImportResultResponse(BaseModel):
    import_job_id: int
    imported_count: int
    duplicate_count: int
    unmatched_count: int
    failed_count: int
    unmatched_payments: list[BillingUnmatchedPaymentResponse]
    rows: list[BillingPaymentImportRowResponse] = Field(default_factory=list)


class EmailHealthResponse(BaseModel):
    status: str
    host: str | None = None
    port: int | None = None
    use_tls: bool | None = None
    message: str | None = None


class TestEmailRequest(BaseModel):
    recipient_email: str

    @field_validator("recipient_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip()
        if not EMAIL_RE.match(normalized):
            raise ValueError("Invalid email format")
        return normalized


class TestEmailResponse(BaseModel):
    to: str
    subject: str
    body_preview: str
    html_preview: str
    email_enabled: bool
    delivery_status: str
    attachments: list[EmailAttachmentResponse] = Field(default_factory=list)
