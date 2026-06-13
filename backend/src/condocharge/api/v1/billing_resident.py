from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from condocharge.api.deps import CurrentUser, DbSession
from condocharge.api.v1._helpers import build_session_response
from condocharge.app.services.billing_service import BillingService
from condocharge.app.services.pdf_statement_service import render_statement_pdf
from condocharge.models.billing import BillingPayment, BillingPaymentEvent, ResidentBillingStatement, ResidentBillingStatementSession
from condocharge.schemas.billing import (
    BillingPaymentEventResponse,
    BillingPaymentResponse,
    BillingStatementDetailResponse,
    BillingStatementResponse,
)


router = APIRouter(prefix="/resident/billing", tags=["resident-billing"])


def _require_resident(current_user: CurrentUser) -> None:
    if current_user.role != "resident":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def _statement_response(statement: ResidentBillingStatement) -> BillingStatementResponse:
    return BillingStatementResponse(
        id=statement.id,
        billing_period_id=statement.billing_period_id,
        period_name=statement.billing_period.name,
        resident_app_user_id=statement.resident_app_user_id,
        resident_username=statement.resident.username,
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


def _payment_event_response(event: BillingPaymentEvent) -> BillingPaymentEventResponse:
    return BillingPaymentEventResponse(
        id=event.id,
        changed_by_app_user_id=event.changed_by_app_user_id,
        changed_by_username=str(event.changed_by_user.username),
        old_status=event.old_status,
        new_status=event.new_status,
        note=event.note,
        created_at=event.created_at,
    )


def _payment_response(payment: BillingPayment) -> BillingPaymentResponse:
    return BillingPaymentResponse(
        id=payment.id,
        statement_id=payment.statement_id,
        amount_eur=float(payment.amount_eur),
        method=payment.method,
        transaction_reference=payment.transaction_reference,
        note=payment.note,
        received_at=payment.received_at,
        created_by_app_user_id=payment.created_by_app_user_id,
        created_by_username=str(payment.created_by_user.username),
        created_at=payment.created_at,
    )


@router.get("/statements", response_model=list[BillingStatementResponse], summary="List resident billing statements")
def resident_billing_statements(db: DbSession, current_user: CurrentUser) -> list[BillingStatementResponse]:
    _require_resident(current_user)
    rows = db.scalars(
        select(ResidentBillingStatement)
        .options(
            joinedload(ResidentBillingStatement.billing_period),
            joinedload(ResidentBillingStatement.resident),
        )
        .where(ResidentBillingStatement.resident_app_user_id == current_user.id)
        .order_by(ResidentBillingStatement.generated_at.desc(), ResidentBillingStatement.id.desc())
    ).all()
    return [_statement_response(row) for row in rows]


@router.get(
    "/statements/{statement_id}",
    response_model=BillingStatementDetailResponse,
    summary="Get resident billing statement detail",
)
def resident_billing_statement_detail(
    db: DbSession,
    current_user: CurrentUser,
    statement_id: int,
) -> BillingStatementDetailResponse:
    _require_resident(current_user)
    service = BillingService(db=db)
    statement = service.get_statement_for_resident(
        condominium_id=current_user.condominium_id,
        resident_id=current_user.id,
        statement_id=statement_id,
    )
    session_links = sorted(
        statement.session_links,
        key=lambda link: (link.charging_session.end_time, link.charging_session.id),
    )
    payments = sorted(statement.payments, key=lambda p: (p.received_at, p.id), reverse=True)
    return BillingStatementDetailResponse(
        **_statement_response(statement).model_dump(),
        period_start=statement.billing_period.period_start,
        period_end=statement.billing_period.period_end,
        energy_price_eur_per_kwh_snapshot=float(statement.billing_period.energy_price_eur_per_kwh_snapshot),
        sessions=[build_session_response(link.charging_session) for link in session_links],
        payment_history=[_payment_event_response(event) for event in sorted(statement.payment_events, key=lambda event: (event.created_at, event.id), reverse=True)],
        payments=[_payment_response(payment) for payment in payments],
    )


@router.get("/statements/{statement_id}/export.pdf", summary="Export resident billing statement as PDF")
def resident_billing_statement_pdf(
    db: DbSession,
    current_user: CurrentUser,
    statement_id: int,
) -> Response:
    _require_resident(current_user)
    service = BillingService(db=db)
    statement = service.get_statement_for_resident(
        condominium_id=current_user.condominium_id,
        resident_id=current_user.id,
        statement_id=statement_id,
    )
    pdf_bytes = render_statement_pdf(condominium_name=current_user.condominium.name, statement=statement)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{statement.statement_number}.pdf"'},
    )
