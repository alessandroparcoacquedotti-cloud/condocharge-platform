from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, TypedDict, cast

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from condocharge.api.deps import AdminUser, DbSession
from condocharge.api.v1._helpers import build_session_response
from condocharge.app.services.billing_service import BillingService
from condocharge.app.services.email_service import EmailAttachment, EmailDeliveryError, EmailService
from condocharge.app.services.email_templates import (
    EmailTemplateContent,
    build_receipt_email,
    build_reminder_email,
    build_statement_email,
)
from condocharge.app.services.pdf_statement_service import render_statement_pdf
from condocharge.core.config import get_settings
from condocharge.models.billing import (
    BillingEmailNotification,
    BillingPayment,
    BillingPaymentEvent,
    BillingPaymentImportJob,
    BillingPaymentImportRow,
    BillingPeriod,
    BillingReminderRule,
    BillingUnmatchedPayment,
    ResidentBillingStatement,
    ResidentBillingStatementSession,
)
from condocharge.models.charging import ChargingSession
from condocharge.models.tenancy import AppUser
from condocharge.schemas.billing import (
    BillingEmailNotificationResponse,
    BillingPaymentEventResponse,
    BillingPaymentImportJobDetailResponse,
    BillingPaymentImportJobSummaryResponse,
    BillingPaymentImportRowResponse,
    BillingPaymentResponse,
    BillingPeriodDetailResponse,
    BillingPeriodResponse,
    BillingReminderRuleResponse,
    BillingStatementDetailResponse,
    BillingStatementResponse,
    BillingUnmatchedPaymentResponse,
    CreateBillingPaymentRequest,
    CreateBillingPeriodRequest,
    EmailAttachmentResponse,
    IgnoreUnmatchedPaymentRequest,
    MatchUnmatchedPaymentRequest,
    PaymentImportResultResponse,
    ReceiptPayloadResponse,
    ReconciliationResponse,
    ReconciliationRow,
    ReminderPayloadResponse,
    ReminderRunResponse,
    SettlementSummaryResponse,
    StatementPayloadResponse,
    UpdateBillingReminderRuleRequest,
    UpdateStatementPaymentStatusRequest,
    WaiveStatementRequest,
)

router = APIRouter(prefix="/admin/billing", tags=["admin-billing"])
MAX_IMPORT_FILE_SIZE_BYTES = 2 * 1024 * 1024
ALLOWED_CSV_CONTENT_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel", ""}


@dataclass(frozen=True)
class _EmailDeliveryResult:
    notification: BillingEmailNotification
    attachment_metadata: list[EmailAttachmentResponse]


class _SettlementSummaryData(TypedDict):
    total_billed_eur: float
    paid_eur: float
    unpaid_eur: float
    waived_eur: float
    partially_paid_eur: float
    collection_rate: float
    open_periods: int
    closed_periods: int


class _PaymentImportResultData(TypedDict):
    job: BillingPaymentImportJob
    imported_count: int
    duplicate_count: int
    unmatched_count: int
    failed_count: int
    unmatched_payments: list[BillingUnmatchedPayment]
    rows: list[BillingPaymentImportRow]


def _run_import_job(
    *,
    db: DbSession,
    condominium_id: int,
    created_by_app_user_id: int,
    job_id: int,
    csv_text: str,
) -> None:
    service = BillingService(db=db)
    try:
        service.process_import_job(
            condominium_id=condominium_id,
            job_id=job_id,
            created_by_app_user_id=created_by_app_user_id,
            csv_text=csv_text,
        )
    except Exception:
        return


def _normalize_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _statement_resident(statement: ResidentBillingStatement) -> AppUser:
    return cast(AppUser, statement.resident)


def _payment_actor(payment: BillingPayment) -> AppUser:
    return cast(AppUser, payment.created_by_user)


def _payment_event_actor(event: BillingPaymentEvent) -> AppUser:
    return cast(AppUser, event.changed_by_user)


def _notification_actor(notification: BillingEmailNotification) -> AppUser:
    return cast(AppUser, notification.created_by_user)


def _linked_session(link: ResidentBillingStatementSession) -> ChargingSession:
    return cast(ChargingSession, link.charging_session)


def _payment_in_received_range(
    payment: BillingPayment,
    *,
    normalized_received_from: datetime | None,
    normalized_received_to: datetime | None,
) -> bool:
    received_at = _normalize_utc(payment.received_at)
    if normalized_received_from is not None and (received_at is None or received_at < normalized_received_from):
        return False
    return normalized_received_to is None or (received_at is not None and received_at <= normalized_received_to)


def _to_statement_response(statement: ResidentBillingStatement) -> BillingStatementResponse:
    resident = _statement_resident(statement)
    return BillingStatementResponse(
        id=statement.id,
        billing_period_id=statement.billing_period_id,
        period_name=statement.billing_period.name,
        resident_app_user_id=statement.resident_app_user_id,
        resident_username=str(resident.username),
        statement_number=statement.statement_number,
        payment_reference=statement.payment_reference,
        sessions_count=statement.sessions_count,
        energy_kwh=float(statement.energy_kwh),
        amount_eur=float(statement.amount_eur),
        amount_paid_eur=float(statement.amount_paid_eur),
        amount_due_eur=float(statement.amount_due_eur),
        payment_status=statement.payment_status,
        generated_at=statement.generated_at,
        paid_at=statement.paid_at,
        last_reminder_at=statement.last_reminder_at,
        reminder_count=int(statement.reminder_count),
    )


def _to_period_response(period: BillingPeriod) -> BillingPeriodResponse:
    statements_total = sum(Decimal(str(s.amount_eur)) for s in period.statements)
    return BillingPeriodResponse(
        id=period.id,
        condominium_id=period.condominium_id,
        name=period.name,
        period_start=period.period_start,
        period_end=period.period_end,
        status=period.status,
        energy_price_eur_per_kwh_snapshot=float(period.energy_price_eur_per_kwh_snapshot),
        created_at=period.created_at,
        closed_at=period.closed_at,
        statements_count=len(period.statements),
        statements_total_amount_eur=float(statements_total),
        unassigned_sessions_count=int(period.unassigned_sessions_count),
        unassigned_energy_kwh=float(period.unassigned_energy_kwh),
        unassigned_amount_eur=float(period.unassigned_amount_eur),
    )


def _to_period_detail_response(period: BillingPeriod) -> BillingPeriodDetailResponse:
    base = _to_period_response(period)
    statements = sorted(period.statements, key=lambda s: (_statement_resident(s).username.lower(), s.id))
    return BillingPeriodDetailResponse(
        **base.model_dump(),
        statements=[_to_statement_response(statement) for statement in statements],
    )


def _to_payment_event_response(event: BillingPaymentEvent) -> BillingPaymentEventResponse:
    actor = _payment_event_actor(event)
    return BillingPaymentEventResponse(
        id=event.id,
        changed_by_app_user_id=event.changed_by_app_user_id,
        changed_by_username=str(actor.username),
        old_status=event.old_status,
        new_status=event.new_status,
        note=event.note,
        created_at=event.created_at,
    )


def _to_payment_response(payment: BillingPayment) -> BillingPaymentResponse:
    actor = _payment_actor(payment)
    return BillingPaymentResponse(
        id=payment.id,
        statement_id=payment.statement_id,
        amount_eur=float(payment.amount_eur),
        method=payment.method,
        transaction_reference=payment.transaction_reference,
        note=payment.note,
        received_at=payment.received_at,
        created_by_app_user_id=payment.created_by_app_user_id,
        created_by_username=str(actor.username),
        created_at=payment.created_at,
    )


def _to_notification_response(notification: BillingEmailNotification) -> BillingEmailNotificationResponse:
    actor = _notification_actor(notification)
    return BillingEmailNotificationResponse(
        id=notification.id,
        statement_id=notification.statement_id,
        recipient_email=notification.recipient_email,
        notification_type=notification.notification_type,
        subject=notification.subject,
        body_preview=notification.body_preview,
        status=notification.status,
        error_message=notification.error_message,
        sent_at=notification.sent_at,
        retry_of_notification_id=notification.retry_of_notification_id,
        created_by_app_user_id=notification.created_by_app_user_id,
        created_by_username=str(actor.username),
        created_at=notification.created_at,
    )


def _to_unmatched_payment_response(row: BillingUnmatchedPayment) -> BillingUnmatchedPaymentResponse:
    return BillingUnmatchedPaymentResponse(
        id=row.id,
        condominium_id=row.condominium_id,
        raw_reference=row.raw_reference,
        amount_eur=float(row.amount_eur),
        received_at=row.received_at,
        transaction_reference=row.transaction_reference,
        method=row.method,
        note=row.note,
        status=row.status,
        matched_statement_id=row.matched_statement_id,
        created_at=row.created_at,
    )


def _to_attachment_response(attachment: EmailAttachment) -> EmailAttachmentResponse:
    return EmailAttachmentResponse(
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=len(attachment.content_bytes),
    )


def _statement_pdf_attachment(
    *,
    condominium_name: str,
    statement: ResidentBillingStatement,
) -> EmailAttachment:
    pdf_bytes = render_statement_pdf(condominium_name=condominium_name, statement=statement)
    return EmailAttachment(
        filename=f"{statement.statement_number}.pdf",
        content_type="application/pdf",
        content_bytes=pdf_bytes,
    )


def _template_for_notification(
    *,
    condominium_name: str,
    statement: ResidentBillingStatement,
    notification_type: str,
) -> EmailTemplateContent:
    if notification_type == "reminder":
        return build_reminder_email(condominium_name=condominium_name, statement=statement)
    if notification_type == "receipt":
        return build_receipt_email(condominium_name=condominium_name, statement=statement)
    return build_statement_email(condominium_name=condominium_name, statement=statement)


def _statement_email_attachments(
    *,
    condominium_name: str,
    statement: ResidentBillingStatement,
    notification_type: str,
) -> list[EmailAttachment]:
    if notification_type not in {"reminder", "receipt", "statement"}:
        return []
    return [_statement_pdf_attachment(condominium_name=condominium_name, statement=statement)]


def _to_import_row_response(row: BillingPaymentImportRow) -> BillingPaymentImportRowResponse:
    return BillingPaymentImportRowResponse(
        id=row.id,
        import_job_id=row.import_job_id,
        row_number=row.row_number,
        raw_payment_reference=row.raw_payment_reference,
        raw_statement_number=row.raw_statement_number,
        amount_eur=float(row.amount_eur) if row.amount_eur is not None else None,
        received_at=row.received_at,
        transaction_reference=row.transaction_reference,
        method=row.method,
        status=row.status,
        matched_statement_id=row.matched_statement_id,
        unmatched_payment_id=row.unmatched_payment_id,
        error_message=row.error_message,
        created_at=row.created_at,
    )


def _to_import_job_summary_response(job: BillingPaymentImportJob) -> BillingPaymentImportJobSummaryResponse:
    actor = cast(AppUser, job.created_by_user)
    return BillingPaymentImportJobSummaryResponse(
        id=job.id,
        condominium_id=job.condominium_id,
        filename=job.filename,
        status=job.status,
        rows_total=int(job.rows_total),
        rows_processed=int(getattr(job, "rows_processed", 0) or 0),
        progress_percent=int(getattr(job, "progress_percent", 0) or 0),
        rows_matched=int(job.rows_matched),
        rows_unmatched=int(job.rows_unmatched),
        rows_duplicate=int(job.rows_duplicate),
        rows_failed=int(job.rows_failed),
        error_message=job.error_message,
        created_by_app_user_id=job.created_by_app_user_id,
        created_by_username=str(actor.username),
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


def _to_import_job_detail_response(job: BillingPaymentImportJob) -> BillingPaymentImportJobDetailResponse:
    return BillingPaymentImportJobDetailResponse(
        **_to_import_job_summary_response(job).model_dump(),
        rows=[_to_import_row_response(row) for row in sorted(job.rows, key=lambda item: (item.row_number, item.id))],
    )


def _decode_csv_upload(*, upload: UploadFile, raw_bytes: bytes) -> str:
    filename = upload.filename or "payments.csv"
    if not filename.lower().endswith(".csv") and upload.content_type not in ALLOWED_CSV_CONTENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only CSV uploads are supported")
    if upload.content_type not in ALLOWED_CSV_CONTENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported CSV content type")
    if len(raw_bytes) > MAX_IMPORT_FILE_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV upload exceeds the 2 MB limit")
    if len(raw_bytes) == 0 or not raw_bytes.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded CSV file is empty")
    try:
        csv_text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV file must be UTF-8 text") from exc
    if not csv_text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded CSV file is empty")
    return csv_text


def _deliver_statement_email(
    *,
    service: BillingService,
    admin_user: AdminUser,
    statement: ResidentBillingStatement,
    notification_type: str,
    target_email: str | None = None,
    retry_of_notification_id: int | None = None,
) -> _EmailDeliveryResult:
    settings = get_settings()
    email_service = EmailService(settings=settings)
    template = _template_for_notification(
        condominium_name=admin_user.condominium.name,
        statement=statement,
        notification_type=notification_type,
    )
    attachments = _statement_email_attachments(
        condominium_name=admin_user.condominium.name,
        statement=statement,
        notification_type=notification_type,
    )
    attachment_metadata = [_to_attachment_response(attachment) for attachment in attachments]
    resident = _statement_resident(statement)
    recipient = target_email or resident.email or resident.username

    if not email_service.enabled:
        notification = service.create_email_notification(
            statement_id=statement.id,
            recipient_email=recipient,
            notification_type=notification_type,
            subject=template.subject,
            body_preview=template.text_body,
            status="preview",
            created_by_app_user_id=admin_user.id,
            retry_of_notification_id=retry_of_notification_id,
        )
        return _EmailDeliveryResult(notification=notification, attachment_metadata=attachment_metadata)

    if not resident.email:
        notification = service.create_email_notification(
            statement_id=statement.id,
            recipient_email=recipient,
            notification_type=notification_type,
            subject=template.subject,
            body_preview=template.text_body,
            status="failed",
            error_message="Resident email is required when email delivery is enabled",
            created_by_app_user_id=admin_user.id,
            retry_of_notification_id=retry_of_notification_id,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Resident email is required when email delivery is enabled")

    try:
        email_service.send(
            to_email=resident.email,
            subject=template.subject,
            text_body=template.text_body,
            html_body=template.html_body,
            attachments=attachments,
        )
        notification = service.create_email_notification(
            statement_id=statement.id,
            recipient_email=resident.email,
            notification_type=notification_type,
            subject=template.subject,
            body_preview=template.text_body,
            status="sent",
            created_by_app_user_id=admin_user.id,
            sent_at=datetime.now(tz=UTC),
            retry_of_notification_id=retry_of_notification_id,
        )
        return _EmailDeliveryResult(notification=notification, attachment_metadata=attachment_metadata)
    except EmailDeliveryError as exc:
        notification = service.create_email_notification(
            statement_id=statement.id,
            recipient_email=resident.email,
            notification_type=notification_type,
            subject=template.subject,
            body_preview=template.text_body,
            status="failed",
            error_message=str(exc),
            created_by_app_user_id=admin_user.id,
            retry_of_notification_id=retry_of_notification_id,
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Email delivery failed: {exc}") from exc


def _to_statement_detail_response(statement: ResidentBillingStatement) -> BillingStatementDetailResponse:
    session_links = sorted(statement.session_links, key=lambda link: (_linked_session(link).end_time, _linked_session(link).id))
    payment_history = sorted(statement.payment_events, key=lambda event: (event.created_at, event.id), reverse=True)
    payments = sorted(statement.payments, key=lambda p: (p.received_at, p.id), reverse=True)
    notifications = sorted(statement.email_notifications, key=lambda n: (n.created_at, n.id), reverse=True)
    return BillingStatementDetailResponse(
        **_to_statement_response(statement).model_dump(),
        period_start=statement.billing_period.period_start,
        period_end=statement.billing_period.period_end,
        energy_price_eur_per_kwh_snapshot=float(statement.billing_period.energy_price_eur_per_kwh_snapshot),
        sessions=[build_session_response(_linked_session(link)) for link in session_links],
        payment_history=[_to_payment_event_response(event) for event in payment_history],
        payments=[_to_payment_response(payment) for payment in payments],
        notifications=[_to_notification_response(notification) for notification in notifications],
    )


@router.get("/periods", response_model=list[BillingPeriodResponse], summary="List billing periods for the current condominium")
def list_billing_periods(db: DbSession, admin_user: AdminUser) -> list[BillingPeriodResponse]:
    periods = db.scalars(
        select(BillingPeriod)
        .options(joinedload(BillingPeriod.statements).joinedload(ResidentBillingStatement.resident))
        .where(BillingPeriod.condominium_id == admin_user.condominium_id)
        .order_by(BillingPeriod.period_start.desc(), BillingPeriod.id.desc())
    ).unique().all()
    return [_to_period_response(period) for period in periods]


@router.post(
    "/periods",
    response_model=BillingPeriodResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a billing period",
)
def create_billing_period(
    db: DbSession,
    admin_user: AdminUser,
    body: CreateBillingPeriodRequest,
) -> BillingPeriodResponse:
    service = BillingService(db=db)
    period = service.create_period(
        condominium=admin_user.condominium,
        name=body.name,
        period_start=body.period_start,
        period_end=body.period_end,
    )
    period = service.get_period_for_admin(condominium_id=admin_user.condominium_id, period_id=period.id)
    return _to_period_response(period)


@router.get("/periods/{period_id}", response_model=BillingPeriodDetailResponse, summary="Get billing period detail")
def get_billing_period(db: DbSession, admin_user: AdminUser, period_id: int) -> BillingPeriodDetailResponse:
    service = BillingService(db=db)
    period = service.get_period_for_admin(condominium_id=admin_user.condominium_id, period_id=period_id)
    return _to_period_detail_response(period)


@router.post("/periods/{period_id}/generate", response_model=BillingPeriodDetailResponse, summary="Generate statements for a billing period")
def generate_billing_period(db: DbSession, admin_user: AdminUser, period_id: int) -> BillingPeriodDetailResponse:
    service = BillingService(db=db)
    period = service.get_period_for_admin(condominium_id=admin_user.condominium_id, period_id=period_id)
    generated = service.generate_period(condominium=admin_user.condominium, period=period)
    return _to_period_detail_response(generated)


@router.post("/periods/{period_id}/close", response_model=BillingPeriodDetailResponse, summary="Close a billing period")
def close_billing_period(db: DbSession, admin_user: AdminUser, period_id: int) -> BillingPeriodDetailResponse:
    service = BillingService(db=db)
    period = service.get_period_for_admin(condominium_id=admin_user.condominium_id, period_id=period_id)
    closed = service.close_period(condominium=admin_user.condominium, period=period)
    return _to_period_detail_response(closed)


@router.patch(
    "/statements/{statement_id}/payment-status",
    response_model=BillingStatementResponse,
    summary="Update statement payment status",
)
def update_statement_payment_status(
    db: DbSession,
    admin_user: AdminUser,
    statement_id: int,
    body: UpdateStatementPaymentStatusRequest,
) -> BillingStatementResponse:
    service = BillingService(db=db)
    statement = service.update_payment_status(
        condominium_id=admin_user.condominium_id,
        changed_by_app_user_id=admin_user.id,
        statement_id=statement_id,
        payment_status=body.payment_status,
        note=body.note,
    )
    return _to_statement_response(statement)


@router.get("/statements/{statement_id}", response_model=BillingStatementDetailResponse, summary="Get billing statement detail")
def get_statement_detail(db: DbSession, admin_user: AdminUser, statement_id: int) -> BillingStatementDetailResponse:
    service = BillingService(db=db)
    statement = service.get_statement_for_admin(condominium_id=admin_user.condominium_id, statement_id=statement_id)
    return _to_statement_detail_response(statement)


@router.get("/statements/{statement_id}/export.pdf", summary="Export billing statement as PDF")
def export_statement_pdf(db: DbSession, admin_user: AdminUser, statement_id: int) -> Response:
    service = BillingService(db=db)
    statement = service.get_statement_for_admin(condominium_id=admin_user.condominium_id, statement_id=statement_id)
    pdf_bytes = render_statement_pdf(condominium_name=admin_user.condominium.name, statement=statement)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{statement.statement_number}.pdf"'},
    )


@router.get("/settlement/summary", response_model=SettlementSummaryResponse, summary="Get settlement summary")
def get_settlement_summary(db: DbSession, admin_user: AdminUser) -> SettlementSummaryResponse:
    service = BillingService(db=db)
    summary = cast(_SettlementSummaryData, service.settlement_summary(condominium_id=admin_user.condominium_id))
    return SettlementSummaryResponse(**summary)


@router.post(
    "/statements/{statement_id}/payments",
    response_model=BillingPaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a payment record to a statement",
)
def add_statement_payment(
    db: DbSession,
    admin_user: AdminUser,
    statement_id: int,
    body: CreateBillingPaymentRequest,
) -> BillingPaymentResponse:
    service = BillingService(db=db)
    payment = service.add_payment(
        condominium_id=admin_user.condominium_id,
        statement_id=statement_id,
        created_by_app_user_id=admin_user.id,
        amount_eur=Decimal(str(body.amount_eur)),
        method=body.method,
        transaction_reference=body.transaction_reference,
        note=body.note,
        received_at=body.received_at,
    )
    statement = service.get_statement_for_admin(condominium_id=admin_user.condominium_id, statement_id=statement_id)
    created = next(p for p in statement.payments if p.id == payment.id)
    return _to_payment_response(created)


@router.get(
    "/statements/{statement_id}/payments",
    response_model=list[BillingPaymentResponse],
    summary="List payment records for a statement",
)
def list_statement_payments(db: DbSession, admin_user: AdminUser, statement_id: int) -> list[BillingPaymentResponse]:
    service = BillingService(db=db)
    payments = service.list_payments(condominium_id=admin_user.condominium_id, statement_id=statement_id)
    return [_to_payment_response(payment) for payment in payments]


@router.patch(
    "/statements/{statement_id}/waive",
    response_model=BillingStatementResponse,
    summary="Waive a statement (admin only)",
)
def waive_statement(db: DbSession, admin_user: AdminUser, statement_id: int, body: WaiveStatementRequest) -> BillingStatementResponse:
    service = BillingService(db=db)
    statement = service.waive_statement(
        condominium_id=admin_user.condominium_id,
        statement_id=statement_id,
        changed_by_app_user_id=admin_user.id,
        note=body.note,
    )
    return _to_statement_response(statement)


@router.post(
    "/statements/{statement_id}/reminder",
    response_model=ReminderPayloadResponse,
    summary="Create reminder metadata payload (no email sending)",
)
def create_reminder(db: DbSession, admin_user: AdminUser, statement_id: int) -> ReminderPayloadResponse:
    service = BillingService(db=db)
    statement = service.create_reminder_metadata(condominium_id=admin_user.condominium_id, statement_id=statement_id)
    template = _template_for_notification(
        condominium_name=admin_user.condominium.name,
        statement=statement,
        notification_type="reminder",
    )
    delivery = _deliver_statement_email(
        service=service,
        admin_user=admin_user,
        statement=statement,
        notification_type="reminder",
    )
    resident = _statement_resident(statement)
    to_value = resident.email or resident.username
    return ReminderPayloadResponse(
        to=to_value,
        resident_username=resident.username,
        statement_number=statement.statement_number,
        subject=template.subject,
        body_preview=template.text_body,
        html_preview=template.html_body,
        amount_due_eur=float(statement.amount_due_eur),
        payment_reference=statement.payment_reference,
        period=statement.billing_period.name,
        email_enabled=bool(get_settings().email_enabled),
        delivery_status=delivery.notification.status,
        notification_id=delivery.notification.id,
        attachments=delivery.attachment_metadata,
    )


def _to_reminder_rule_response(rule: BillingReminderRule) -> BillingReminderRuleResponse:
    return BillingReminderRuleResponse(
        id=rule.id,
        condominium_id=rule.condominium_id,
        enabled=bool(rule.enabled),
        days_after_period_close=int(rule.days_after_period_close),
        repeat_every_days=int(rule.repeat_every_days),
        max_reminders=int(rule.max_reminders),
        min_amount_due_eur=float(rule.min_amount_due_eur),
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.get(
    "/reminders/rule",
    response_model=BillingReminderRuleResponse,
    summary="Get reminder rule configuration for the current condominium",
)
def get_reminder_rule(db: DbSession, admin_user: AdminUser) -> BillingReminderRuleResponse:
    service = BillingService(db=db)
    rule = service.get_or_create_reminder_rule(condominium_id=admin_user.condominium_id)
    return _to_reminder_rule_response(rule)


@router.put(
    "/reminders/rule",
    response_model=BillingReminderRuleResponse,
    summary="Update reminder rule configuration for the current condominium",
)
def update_reminder_rule(db: DbSession, admin_user: AdminUser, body: UpdateBillingReminderRuleRequest) -> BillingReminderRuleResponse:
    service = BillingService(db=db)
    rule = service.update_reminder_rule(
        condominium_id=admin_user.condominium_id,
        enabled=body.enabled,
        days_after_period_close=body.days_after_period_close,
        repeat_every_days=body.repeat_every_days,
        max_reminders=body.max_reminders,
        min_amount_due_eur=Decimal(str(body.min_amount_due_eur)),
    )
    return _to_reminder_rule_response(rule)


@router.get(
    "/reminders/candidates",
    response_model=list[BillingStatementResponse],
    summary="List reminder candidates for the current condominium based on reminder rules",
)
def reminder_candidates(db: DbSession, admin_user: AdminUser) -> list[BillingStatementResponse]:
    service = BillingService(db=db)
    now = datetime.now(tz=UTC)
    candidates = service.reminder_candidates(condominium_id=admin_user.condominium_id, now=now)
    return [_to_statement_response(statement) for statement in candidates]


@router.post(
    "/reminders/run",
    response_model=ReminderRunResponse,
    summary="Run reminder batch for all current candidates",
)
def run_reminders(db: DbSession, admin_user: AdminUser) -> ReminderRunResponse:
    service = BillingService(db=db)
    now = datetime.now(tz=UTC)
    rule = service.get_or_create_reminder_rule(condominium_id=admin_user.condominium_id)
    candidates = service.reminder_candidates(condominium_id=admin_user.condominium_id, now=now)
    candidates_count = len(candidates)
    sent_count = 0
    preview_count = 0
    skipped_count = 0
    failed_count = 0

    for candidate in candidates:
        statement = service.get_statement_for_admin(condominium_id=admin_user.condominium_id, statement_id=candidate.id)
        if int(statement.reminder_count or 0) >= int(rule.max_reminders):
            skipped_count += 1
            continue
        if statement.last_reminder_at is not None:
            last = _normalize_utc(statement.last_reminder_at)
            now_utc = _normalize_utc(now)
            if last is not None and now_utc is not None and now_utc < last + timedelta(days=int(rule.repeat_every_days)):
                skipped_count += 1
                continue

        statement = service.create_reminder_metadata(condominium_id=admin_user.condominium_id, statement_id=statement.id)
        try:
            delivery = _deliver_statement_email(
                service=service,
                admin_user=admin_user,
                statement=statement,
                notification_type="reminder",
            )
            if delivery.notification.status == "sent":
                sent_count += 1
            elif delivery.notification.status == "preview":
                preview_count += 1
            else:
                failed_count += 1
        except HTTPException:
            failed_count += 1

    return ReminderRunResponse(
        candidates_count=candidates_count,
        sent_count=sent_count,
        preview_count=preview_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
    )


@router.get(
    "/reconciliation",
    response_model=ReconciliationResponse,
    summary="Reconciliation report across statements",
)
def reconciliation(
    db: DbSession,
    admin_user: AdminUser,
    period_id: Annotated[int | None, Query()] = None,
    resident_id: Annotated[int | None, Query()] = None,
    payment_status: Annotated[str | None, Query()] = None,
    from_date: Annotated[datetime | None, Query()] = None,
    to_date: Annotated[datetime | None, Query()] = None,
    received_from_date: Annotated[datetime | None, Query()] = None,
    received_to_date: Annotated[datetime | None, Query()] = None,
) -> ReconciliationResponse:
    service = BillingService(db=db)
    normalized_received_from = _normalize_utc(received_from_date)
    normalized_received_to = _normalize_utc(received_to_date)
    statements = service.reconciliation_rows(
        condominium_id=admin_user.condominium_id,
        period_id=period_id,
        resident_id=resident_id,
        payment_status=payment_status,
        from_date=from_date,
        to_date=to_date,
        received_from_date=normalized_received_from,
        received_to_date=normalized_received_to,
    )
    active_unmatched_rows = service.list_unmatched_payments(
        condominium_id=admin_user.condominium_id,
        statuses=("unmatched",),
    )
    rows: list[ReconciliationRow] = []
    total_amount = 0.0
    total_paid = 0.0
    total_due = 0.0
    total_received = 0.0
    for statement in statements:
        matching_payments = [
            p
            for p in statement.payments
            if _payment_in_received_range(
                p,
                normalized_received_from=normalized_received_from,
                normalized_received_to=normalized_received_to,
            )
        ]
        last_payment_at = max((p.received_at for p in matching_payments), default=max((p.received_at for p in statement.payments), default=None))
        amount = float(statement.amount_eur)
        paid = float(statement.amount_paid_eur)
        due = float(statement.amount_due_eur)
        total_amount += amount
        total_paid += paid
        total_due += due
        total_received += sum(float(p.amount_eur) for p in matching_payments)
        rows.append(
            ReconciliationRow(
                statement_id=statement.id,
                statement_number=statement.statement_number,
                payment_reference=statement.payment_reference,
                billing_period_id=statement.billing_period_id,
                period_name=statement.billing_period.name,
                resident_app_user_id=statement.resident_app_user_id,
                resident_username=_statement_resident(statement).username,
                amount_eur=amount,
                amount_paid_eur=paid,
                amount_due_eur=due,
                payment_status=statement.payment_status,
                last_payment_at=last_payment_at,
                reminder_count=int(statement.reminder_count),
                last_reminder_at=statement.last_reminder_at,
            )
        )

    return ReconciliationResponse(
        rows=rows,
        total_amount_eur=round(total_amount, 2),
        total_paid_eur=round(total_paid, 2),
        total_due_eur=round(total_due, 2),
        total_received_eur=round(total_received, 2),
        unmatched_payments_count=len(active_unmatched_rows),
        unmatched_payments_amount_eur=round(sum(float(row.amount_eur) for row in active_unmatched_rows), 2),
        unmatched_payments=[_to_unmatched_payment_response(row) for row in active_unmatched_rows],
    )


@router.post(
    "/statements/{statement_id}/receipt",
    response_model=ReceiptPayloadResponse,
    summary="Send or preview receipt email for a paid statement",
)
def send_receipt(db: DbSession, admin_user: AdminUser, statement_id: int) -> ReceiptPayloadResponse:
    service = BillingService(db=db)
    statement = service.get_statement_for_admin(condominium_id=admin_user.condominium_id, statement_id=statement_id)
    if statement.payment_status != "paid":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Receipt can only be sent for paid statements")

    template = _template_for_notification(
        condominium_name=admin_user.condominium.name,
        statement=statement,
        notification_type="receipt",
    )
    delivery = _deliver_statement_email(
        service=service,
        admin_user=admin_user,
        statement=statement,
        notification_type="receipt",
    )
    latest_payment_date = max((payment.received_at for payment in statement.payments), default=statement.paid_at)
    resident = _statement_resident(statement)
    return ReceiptPayloadResponse(
        to=resident.email or resident.username,
        resident_username=resident.username,
        statement_number=statement.statement_number,
        subject=template.subject,
        body_preview=template.text_body,
        html_preview=template.html_body,
        amount_eur=float(statement.amount_eur),
        amount_paid_eur=float(statement.amount_paid_eur),
        payment_reference=statement.payment_reference,
        payment_date=latest_payment_date,
        email_enabled=bool(get_settings().email_enabled),
        delivery_status=delivery.notification.status,
        notification_id=delivery.notification.id,
        attachments=delivery.attachment_metadata,
    )


@router.post(
    "/statements/{statement_id}/send",
    response_model=StatementPayloadResponse,
    summary="Send or preview statement email for a statement",
)
def send_statement(db: DbSession, admin_user: AdminUser, statement_id: int) -> StatementPayloadResponse:
    service = BillingService(db=db)
    statement = service.get_statement_for_admin(condominium_id=admin_user.condominium_id, statement_id=statement_id)
    template = _template_for_notification(
        condominium_name=admin_user.condominium.name,
        statement=statement,
        notification_type="statement",
    )
    delivery = _deliver_statement_email(
        service=service,
        admin_user=admin_user,
        statement=statement,
        notification_type="statement",
    )
    resident = _statement_resident(statement)
    return StatementPayloadResponse(
        to=resident.email or resident.username,
        resident_username=resident.username,
        statement_number=statement.statement_number,
        subject=template.subject,
        body_preview=template.text_body,
        html_preview=template.html_body,
        amount_eur=float(statement.amount_eur),
        amount_due_eur=float(statement.amount_due_eur),
        payment_reference=statement.payment_reference,
        period=statement.billing_period.name,
        email_enabled=bool(get_settings().email_enabled),
        delivery_status=delivery.notification.status,
        notification_id=delivery.notification.id,
        attachments=delivery.attachment_metadata,
    )


@router.post(
    "/payments/import.csv",
    response_model=PaymentImportResultResponse,
    summary="Import payments from CSV content",
)
def import_payments_csv(
    db: DbSession,
    admin_user: AdminUser,
    background_tasks: BackgroundTasks,
    csv_body: str = Body(..., media_type="text/csv"),
    async_mode: Annotated[bool, Query()] = False,
) -> PaymentImportResultResponse:
    if not csv_body.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV body is empty")
    service = BillingService(db=db)
    if async_mode:
        job = service.create_import_job(
            condominium_id=admin_user.condominium_id,
            filename="payments.csv",
            created_by_app_user_id=admin_user.id,
        )
        background_tasks.add_task(
            _run_import_job,
            db=db,
            condominium_id=admin_user.condominium_id,
            created_by_app_user_id=admin_user.id,
            job_id=job.id,
            csv_text=csv_body,
        )
        return PaymentImportResultResponse(
            import_job_id=int(job.id),
            imported_count=0,
            duplicate_count=0,
            unmatched_count=0,
            failed_count=0,
            unmatched_payments=[],
            rows=[],
        )

    result = cast(
        _PaymentImportResultData,
        service.import_payments_csv(
        condominium_id=admin_user.condominium_id,
        created_by_app_user_id=admin_user.id,
        csv_text=csv_body,
        filename="payments.csv",
        ),
    )
    return PaymentImportResultResponse(
        import_job_id=int(result["job"].id),
        imported_count=int(result["imported_count"]),
        duplicate_count=int(result["duplicate_count"]),
        unmatched_count=int(result["unmatched_count"]),
        failed_count=int(result["failed_count"]),
        unmatched_payments=[_to_unmatched_payment_response(row) for row in result["unmatched_payments"]],
        rows=[_to_import_row_response(row) for row in result["rows"]],
    )


@router.post(
    "/payments/import",
    response_model=PaymentImportResultResponse,
    summary="Import payments from a multipart CSV upload",
)
async def import_payments_upload(
    db: DbSession,
    admin_user: AdminUser,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    async_mode: Annotated[bool, Query()] = False,
) -> PaymentImportResultResponse:
    raw_bytes = await file.read()
    csv_text = _decode_csv_upload(upload=file, raw_bytes=raw_bytes)
    service = BillingService(db=db)
    if async_mode:
        job = service.create_import_job(
            condominium_id=admin_user.condominium_id,
            filename=file.filename or "payments.csv",
            created_by_app_user_id=admin_user.id,
        )
        background_tasks.add_task(
            _run_import_job,
            db=db,
            condominium_id=admin_user.condominium_id,
            created_by_app_user_id=admin_user.id,
            job_id=job.id,
            csv_text=csv_text,
        )
        return PaymentImportResultResponse(
            import_job_id=int(job.id),
            imported_count=0,
            duplicate_count=0,
            unmatched_count=0,
            failed_count=0,
            unmatched_payments=[],
            rows=[],
        )

    result = cast(
        _PaymentImportResultData,
        service.import_payments_csv(
        condominium_id=admin_user.condominium_id,
        created_by_app_user_id=admin_user.id,
        csv_text=csv_text,
        filename=file.filename or "payments.csv",
        ),
    )
    return PaymentImportResultResponse(
        import_job_id=int(result["job"].id),
        imported_count=int(result["imported_count"]),
        duplicate_count=int(result["duplicate_count"]),
        unmatched_count=int(result["unmatched_count"]),
        failed_count=int(result["failed_count"]),
        unmatched_payments=[_to_unmatched_payment_response(row) for row in result["unmatched_payments"]],
        rows=[_to_import_row_response(row) for row in result["rows"]],
    )


@router.get(
    "/payments/import-jobs",
    response_model=list[BillingPaymentImportJobSummaryResponse],
    summary="List payment import jobs for the current condominium",
)
def list_payment_import_jobs(db: DbSession, admin_user: AdminUser) -> list[BillingPaymentImportJobSummaryResponse]:
    service = BillingService(db=db)
    jobs = service.list_import_jobs(condominium_id=admin_user.condominium_id)
    return [_to_import_job_summary_response(job) for job in jobs]


@router.get(
    "/payments/import-jobs/{job_id}",
    response_model=BillingPaymentImportJobDetailResponse,
    summary="Get payment import job detail with row-level results",
)
def get_payment_import_job(db: DbSession, admin_user: AdminUser, job_id: int) -> BillingPaymentImportJobDetailResponse:
    service = BillingService(db=db)
    job = service.get_import_job_for_admin(condominium_id=admin_user.condominium_id, job_id=job_id)
    return _to_import_job_detail_response(job)


@router.get(
    "/payments/import-jobs/{job_id}/errors.csv",
    summary="Export failed/duplicate/unmatched rows for an import job as CSV",
)
def export_import_job_errors_csv(db: DbSession, admin_user: AdminUser, job_id: int) -> Response:
    service = BillingService(db=db)
    job = service.get_import_job_for_admin(condominium_id=admin_user.condominium_id, job_id=job_id)
    error_rows = [row for row in job.rows if row.status in {"failed", "duplicate", "unmatched"}]

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "row_number",
            "raw_payment_reference",
            "raw_statement_number",
            "amount_eur",
            "received_at",
            "transaction_reference",
            "status",
            "error_message",
        ],
    )
    writer.writeheader()
    for row in sorted(error_rows, key=lambda r: (r.row_number, r.id)):
        writer.writerow(
            {
                "row_number": row.row_number,
                "raw_payment_reference": row.raw_payment_reference or "",
                "raw_statement_number": row.raw_statement_number or "",
                "amount_eur": f"{float(row.amount_eur):.2f}" if row.amount_eur is not None else "",
                "received_at": row.received_at.isoformat() if row.received_at else "",
                "transaction_reference": row.transaction_reference or "",
                "status": row.status,
                "error_message": row.error_message or "",
            }
        )
    data = buf.getvalue().encode("utf-8")
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="import-job-{job.id}-errors.csv"'},
    )


@router.post(
    "/unmatched-payments/{unmatched_payment_id}/match",
    response_model=BillingUnmatchedPaymentResponse,
    summary="Match an unmatched imported payment to a statement",
)
def match_unmatched_payment(
    db: DbSession,
    admin_user: AdminUser,
    unmatched_payment_id: int,
    body: MatchUnmatchedPaymentRequest,
) -> BillingUnmatchedPaymentResponse:
    service = BillingService(db=db)
    row = service.match_unmatched_payment(
        condominium_id=admin_user.condominium_id,
        unmatched_payment_id=unmatched_payment_id,
        statement_id=body.statement_id,
        created_by_app_user_id=admin_user.id,
    )
    return _to_unmatched_payment_response(row)


@router.patch(
    "/unmatched-payments/{unmatched_payment_id}/ignore",
    response_model=BillingUnmatchedPaymentResponse,
    summary="Ignore an unmatched imported payment",
)
def ignore_unmatched_payment(
    db: DbSession,
    admin_user: AdminUser,
    unmatched_payment_id: int,
    body: IgnoreUnmatchedPaymentRequest,
) -> BillingUnmatchedPaymentResponse:
    service = BillingService(db=db)
    row = service.ignore_unmatched_payment(
        condominium_id=admin_user.condominium_id,
        unmatched_payment_id=unmatched_payment_id,
        note=body.note,
    )
    return _to_unmatched_payment_response(row)


@router.post(
    "/notifications/{notification_id}/retry",
    response_model=BillingEmailNotificationResponse,
    summary="Retry a failed or preview billing notification",
)
def retry_notification(db: DbSession, admin_user: AdminUser, notification_id: int) -> BillingEmailNotificationResponse:
    service = BillingService(db=db)
    notification = service.get_notification_for_admin(
        condominium_id=admin_user.condominium_id,
        notification_id=notification_id,
    )
    if notification.status not in {"failed", "preview"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only failed or preview notifications can be retried")

    statement = service.get_statement_for_admin(
        condominium_id=admin_user.condominium_id,
        statement_id=notification.statement_id,
    )
    delivery = _deliver_statement_email(
        service=service,
        admin_user=admin_user,
        statement=statement,
        notification_type=notification.notification_type,
        target_email=_statement_resident(statement).email or notification.recipient_email,
        retry_of_notification_id=notification.id,
    )
    retried = service.get_notification_for_admin(
        condominium_id=admin_user.condominium_id,
        notification_id=delivery.notification.id,
    )
    return _to_notification_response(retried)


@router.get("/periods/{period_id}/export.csv", summary="Export a billing period as CSV")
def export_billing_period_csv(db: DbSession, admin_user: AdminUser, period_id: int) -> Response:
    service = BillingService(db=db)
    period = service.get_period_for_admin(condominium_id=admin_user.condominium_id, period_id=period_id)

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "period",
            "resident",
            "sessions_count",
            "energy_kwh",
            "amount_eur",
            "payment_status",
            "period_start",
            "period_end",
        ],
    )
    writer.writeheader()

    for statement in sorted(period.statements, key=lambda s: (_statement_resident(s).username.lower(), s.id)):
        writer.writerow(
            {
                "period": period.name,
                "resident": _statement_resident(statement).username,
                "sessions_count": statement.sessions_count,
                "energy_kwh": f"{float(statement.energy_kwh):.3f}",
                "amount_eur": f"{float(statement.amount_eur):.2f}",
                "payment_status": statement.payment_status,
                "period_start": period.period_start.isoformat(),
                "period_end": period.period_end.isoformat(),
            }
        )

    writer.writerow(
        {
            "period": period.name,
            "resident": "Unassigned",
            "sessions_count": int(period.unassigned_sessions_count),
            "energy_kwh": f"{float(period.unassigned_energy_kwh):.3f}",
            "amount_eur": f"{float(period.unassigned_amount_eur):.2f}",
            "payment_status": "",
            "period_start": period.period_start.isoformat(),
            "period_end": period.period_end.isoformat(),
        }
    )

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="billing_period_{period.id}.csv"'},
    )
