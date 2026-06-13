from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

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
from condocharge.models.tenancy import AppUser, AppUserRole, Condominium

THREE_DP = Decimal("0.001")
TWO_DP = Decimal("0.01")


def _normalize_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class BillingService:
    def __init__(self, *, db: Session) -> None:
        self._db = db

    def get_period_for_admin(self, *, condominium_id: int, period_id: int) -> BillingPeriod:
        period = self._db.execute(
            select(BillingPeriod)
            .options(
                joinedload(BillingPeriod.statements).joinedload(ResidentBillingStatement.resident),
                joinedload(BillingPeriod.statements)
                .joinedload(ResidentBillingStatement.session_links)
                .joinedload(ResidentBillingStatementSession.charging_session)
                .joinedload(ChargingSession.station),
                joinedload(BillingPeriod.statements)
                .joinedload(ResidentBillingStatement.session_links)
                .joinedload(ResidentBillingStatementSession.charging_session)
                .joinedload(ChargingSession.rfid_user),
            )
            .where(BillingPeriod.id == period_id)
        ).unique().scalar_one_or_none()
        if period is None or period.condominium_id != condominium_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Billing period not found")
        return period

    def get_statement_for_admin(self, *, condominium_id: int, statement_id: int) -> ResidentBillingStatement:
        statement = self._db.execute(
            select(ResidentBillingStatement)
            .options(
                joinedload(ResidentBillingStatement.billing_period),
                joinedload(ResidentBillingStatement.resident),
                joinedload(ResidentBillingStatement.payment_events).joinedload(BillingPaymentEvent.changed_by_user),
                joinedload(ResidentBillingStatement.payments).joinedload(BillingPayment.created_by_user),
                joinedload(ResidentBillingStatement.email_notifications).joinedload(BillingEmailNotification.created_by_user),
                joinedload(ResidentBillingStatement.session_links)
                .joinedload(ResidentBillingStatementSession.charging_session)
                .joinedload(ChargingSession.station),
                joinedload(ResidentBillingStatement.session_links)
                .joinedload(ResidentBillingStatementSession.charging_session)
                .joinedload(ChargingSession.rfid_user),
            )
            .where(ResidentBillingStatement.id == statement_id)
        ).unique().scalar_one_or_none()
        if statement is None or statement.billing_period.condominium_id != condominium_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Billing statement not found")
        return statement

    def get_statement_for_resident(self, *, condominium_id: int, resident_id: int, statement_id: int) -> ResidentBillingStatement:
        statement = self._db.execute(
            select(ResidentBillingStatement)
            .options(
                joinedload(ResidentBillingStatement.billing_period),
                joinedload(ResidentBillingStatement.resident),
                joinedload(ResidentBillingStatement.payment_events).joinedload(BillingPaymentEvent.changed_by_user),
                joinedload(ResidentBillingStatement.payments).joinedload(BillingPayment.created_by_user),
                joinedload(ResidentBillingStatement.session_links)
                .joinedload(ResidentBillingStatementSession.charging_session)
                .joinedload(ChargingSession.station),
                joinedload(ResidentBillingStatement.session_links)
                .joinedload(ResidentBillingStatementSession.charging_session)
                .joinedload(ChargingSession.rfid_user),
            )
            .where(ResidentBillingStatement.id == statement_id)
        ).unique().scalar_one_or_none()
        if (
            statement is None
            or statement.billing_period.condominium_id != condominium_id
            or statement.resident_app_user_id != resident_id
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Billing statement not found")
        return statement

    def get_unmatched_payment_for_admin(self, *, condominium_id: int, unmatched_payment_id: int) -> BillingUnmatchedPayment:
        unmatched = self._db.get(BillingUnmatchedPayment, unmatched_payment_id)
        if unmatched is None or unmatched.condominium_id != condominium_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unmatched payment not found")
        return unmatched

    def get_notification_for_admin(self, *, condominium_id: int, notification_id: int) -> BillingEmailNotification:
        notification = self._db.execute(
            select(BillingEmailNotification)
            .options(
                joinedload(BillingEmailNotification.statement)
                .joinedload(ResidentBillingStatement.billing_period),
                joinedload(BillingEmailNotification.statement).joinedload(ResidentBillingStatement.resident),
                joinedload(BillingEmailNotification.statement).joinedload(ResidentBillingStatement.payments),
                joinedload(BillingEmailNotification.created_by_user),
            )
            .where(BillingEmailNotification.id == notification_id)
        ).unique().scalar_one_or_none()
        if notification is None or notification.statement.billing_period.condominium_id != condominium_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
        return notification

    def get_import_job_for_admin(self, *, condominium_id: int, job_id: int) -> BillingPaymentImportJob:
        job = self._db.execute(
            select(BillingPaymentImportJob)
            .options(
                joinedload(BillingPaymentImportJob.created_by_user),
                joinedload(BillingPaymentImportJob.rows),
            )
            .where(BillingPaymentImportJob.id == job_id)
        ).unique().scalar_one_or_none()
        if job is None or job.condominium_id != condominium_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import job not found")
        return job

    def _assert_period_range_valid(
        self,
        *,
        condominium_id: int,
        period_start: datetime,
        period_end: datetime,
    ) -> None:
        if period_end <= period_start:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="period_end must be greater than period_start")

        overlap = self._db.scalar(
            select(BillingPeriod.id)
            .where(BillingPeriod.condominium_id == condominium_id)
            .where(BillingPeriod.period_start < period_end)
            .where(BillingPeriod.period_end > period_start)
            .limit(1)
        )
        if overlap is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Billing period overlaps an existing period in this condominium",
            )

    def _next_statement_identifiers(self, *, condominium_id: int, period_year: int) -> tuple[str, str]:
        prefix = f"CC-{period_year}-"
        rows = self._db.execute(
            select(ResidentBillingStatement.statement_number)
            .join(ResidentBillingStatement.billing_period)
            .where(BillingPeriod.condominium_id == condominium_id)
        ).all()
        max_seq = 0
        for (statement_number,) in rows:
            if isinstance(statement_number, str) and statement_number.startswith(prefix):
                suffix = statement_number.removeprefix(prefix)
                if suffix.isdigit():
                    max_seq = max(max_seq, int(suffix))
        next_seq = max_seq + 1
        statement_number = f"{prefix}{next_seq:04d}"
        payment_reference = f"PAY-{statement_number}"
        return statement_number, payment_reference

    def _match_statement(
        self,
        *,
        condominium_id: int,
        payment_reference: str | None,
        statement_number: str | None,
    ) -> ResidentBillingStatement | None:
        if payment_reference:
            statement = self._db.execute(
                select(ResidentBillingStatement)
                .join(ResidentBillingStatement.billing_period)
                .options(joinedload(ResidentBillingStatement.billing_period), joinedload(ResidentBillingStatement.resident))
                .where(BillingPeriod.condominium_id == condominium_id)
                .where(ResidentBillingStatement.payment_reference == payment_reference)
            ).unique().scalar_one_or_none()
            if statement is not None:
                return statement
        if statement_number:
            statement = self._db.execute(
                select(ResidentBillingStatement)
                .join(ResidentBillingStatement.billing_period)
                .options(joinedload(ResidentBillingStatement.billing_period), joinedload(ResidentBillingStatement.resident))
                .where(BillingPeriod.condominium_id == condominium_id)
                .where(ResidentBillingStatement.statement_number == statement_number)
            ).unique().scalar_one_or_none()
            if statement is not None:
                return statement
        return None

    def _has_duplicate_transaction_reference(self, *, condominium_id: int, transaction_reference: str | None) -> bool:
        if not transaction_reference:
            return False
        existing = self._db.scalar(
            select(BillingPayment.id)
            .join(BillingPayment.statement)
            .join(ResidentBillingStatement.billing_period)
            .where(BillingPeriod.condominium_id == condominium_id)
            .where(BillingPayment.transaction_reference == transaction_reference)
            .limit(1)
        )
        return existing is not None

    def _recompute_amounts_and_status(self, statement: ResidentBillingStatement) -> None:
        if statement.amount_paid_eur < 0:
            statement.amount_paid_eur = Decimal("0")
        if statement.payment_status == "waived":
            statement.amount_due_eur = Decimal("0")
            statement.paid_at = None
            return

        due = Decimal(statement.amount_eur) - Decimal(statement.amount_paid_eur)
        if due < 0:
            due = Decimal("0")
        statement.amount_due_eur = due.quantize(TWO_DP, rounding=ROUND_HALF_UP)

        if statement.amount_paid_eur <= 0:
            statement.payment_status = "unpaid"
            statement.paid_at = None
        elif statement.amount_paid_eur < statement.amount_eur:
            statement.payment_status = "partially_paid"
            statement.paid_at = None
        else:
            statement.payment_status = "paid"
            statement.paid_at = statement.paid_at or datetime.now(tz=UTC)

    def create_period(
        self,
        *,
        condominium: Condominium,
        name: str,
        period_start: datetime,
        period_end: datetime,
    ) -> BillingPeriod:
        self._assert_period_range_valid(
            condominium_id=condominium.id,
            period_start=period_start,
            period_end=period_end,
        )

        period = BillingPeriod(
            condominium_id=condominium.id,
            name=name,
            period_start=period_start,
            period_end=period_end,
            status="draft",
            energy_price_eur_per_kwh_snapshot=condominium.energy_price_eur_per_kwh,
            unassigned_sessions_count=0,
            unassigned_energy_kwh=Decimal("0"),
            unassigned_amount_eur=Decimal("0"),
        )
        self._db.add(period)
        self._db.commit()
        self._db.refresh(period)
        return period

    def generate_period(self, *, condominium: Condominium, period: BillingPeriod) -> BillingPeriod:
        if period.status == "closed":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Closed periods cannot be regenerated")

        price = Decimal(str(condominium.energy_price_eur_per_kwh))
        period.energy_price_eur_per_kwh_snapshot = price

        existing_by_resident = {statement.resident_app_user_id: statement for statement in period.statements}

        sessions = self._db.scalars(
            select(ChargingSession)
            .options(joinedload(ChargingSession.station), joinedload(ChargingSession.rfid_user))
            .where(ChargingSession.condominium_id == condominium.id)
            .where(ChargingSession.start_time >= period.period_start)
            .where(ChargingSession.end_time <= period.period_end)
            .order_by(ChargingSession.start_time.asc(), ChargingSession.id.asc())
        ).all()

        grouped: dict[int, list[ChargingSession]] = defaultdict(list)
        unassigned_sessions: list[ChargingSession] = []
        resident_cache: dict[int, AppUser] = {}

        for session in sessions:
            rfid = session.rfid_user
            if rfid is None or rfid.app_user_id is None:
                unassigned_sessions.append(session)
                continue

            resident = resident_cache.get(rfid.app_user_id)
            if resident is None:
                resident = self._db.get(AppUser, rfid.app_user_id)
                if resident is not None:
                    resident_cache[rfid.app_user_id] = resident
            if resident is None or resident.condominium_id != condominium.id or resident.role != AppUserRole.RESIDENT:
                unassigned_sessions.append(session)
                continue

            grouped[resident.id].append(session)

        now = datetime.now(tz=UTC)
        seen_resident_ids: set[int] = set()
        for resident_id, resident_sessions in grouped.items():
            seen_resident_ids.add(resident_id)
            energy_wh = sum(int(s.energy_wh) for s in resident_sessions)
            energy_kwh = (Decimal(energy_wh) / Decimal(1000)).quantize(THREE_DP, rounding=ROUND_HALF_UP)
            amount_eur = (energy_kwh * price).quantize(TWO_DP, rounding=ROUND_HALF_UP)

            statement = existing_by_resident.get(resident_id)
            if statement is None:
                statement_number, payment_reference = self._next_statement_identifiers(
                    condominium_id=condominium.id,
                    period_year=period.period_start.year,
                )
                statement = ResidentBillingStatement(
                    billing_period_id=period.id,
                    resident_app_user_id=resident_id,
                    sessions_count=len(resident_sessions),
                    energy_kwh=energy_kwh,
                    amount_eur=amount_eur,
                    amount_paid_eur=Decimal("0"),
                    amount_due_eur=amount_eur,
                    statement_number=statement_number,
                    payment_reference=payment_reference,
                    payment_status="unpaid",
                    generated_at=now,
                    reminder_count=0,
                    last_reminder_at=None,
                )
                self._db.add(statement)
                self._db.flush()
            else:
                statement.sessions_count = len(resident_sessions)
                statement.energy_kwh = energy_kwh
                statement.amount_eur = amount_eur
                self._recompute_amounts_and_status(statement)
                for link in list(statement.session_links):
                    self._db.delete(link)
                self._db.flush()

            for session in resident_sessions:
                self._db.add(
                    ResidentBillingStatementSession(
                        statement_id=statement.id,
                        charging_session_id=session.id,
                    )
                )

        for resident_id, statement in existing_by_resident.items():
            if resident_id not in seen_resident_ids:
                self._db.delete(statement)
        self._db.flush()

        unassigned_energy_wh = sum(int(s.energy_wh) for s in unassigned_sessions)
        unassigned_energy_kwh = (Decimal(unassigned_energy_wh) / Decimal(1000)).quantize(THREE_DP, rounding=ROUND_HALF_UP)
        period.unassigned_sessions_count = len(unassigned_sessions)
        period.unassigned_energy_kwh = unassigned_energy_kwh
        period.unassigned_amount_eur = (unassigned_energy_kwh * price).quantize(TWO_DP, rounding=ROUND_HALF_UP)
        period.closed_at = None if period.status == "draft" else period.closed_at

        self._db.commit()
        return self.get_period_for_admin(condominium_id=condominium.id, period_id=period.id)

    def close_period(self, *, condominium: Condominium, period: BillingPeriod) -> BillingPeriod:
        if period.status == "closed":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Billing period already closed")

        if len(period.statements) == 0 and int(period.unassigned_sessions_count or 0) == 0:
            period = self.generate_period(condominium=condominium, period=period)

        period.status = "closed"
        period.closed_at = datetime.now(tz=UTC)
        self._db.commit()
        return self.get_period_for_admin(condominium_id=condominium.id, period_id=period.id)

    def update_payment_status(
        self,
        *,
        condominium_id: int,
        changed_by_app_user_id: int,
        statement_id: int,
        payment_status: str,
        note: str | None,
    ) -> ResidentBillingStatement:
        if payment_status not in {"unpaid", "paid", "waived"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payment status")

        statement = self.get_statement_for_admin(condominium_id=condominium_id, statement_id=statement_id)

        old_status = statement.payment_status
        if old_status == payment_status:
            return statement

        if payment_status == "unpaid":
            statement.amount_paid_eur = Decimal("0")
            statement.payment_status = "unpaid"
            statement.paid_at = None
        elif payment_status == "paid":
            statement.amount_paid_eur = Decimal(statement.amount_eur)
            statement.payment_status = "paid"
            statement.paid_at = datetime.now(tz=UTC)
        else:
            statement.payment_status = "waived"
            statement.amount_due_eur = Decimal("0")
            statement.paid_at = None
        self._recompute_amounts_and_status(statement)
        self._db.add(
            BillingPaymentEvent(
                statement_id=statement.id,
                changed_by_app_user_id=changed_by_app_user_id,
                old_status=old_status,
                new_status=payment_status,
                note=note.strip() if note else None,
            )
        )
        self._db.commit()
        return self.get_statement_for_admin(condominium_id=condominium_id, statement_id=statement.id)

    def add_payment(
        self,
        *,
        condominium_id: int,
        statement_id: int,
        created_by_app_user_id: int,
        amount_eur: Decimal,
        method: str,
        transaction_reference: str | None,
        note: str | None,
        received_at: datetime,
    ) -> BillingPayment:
        if amount_eur <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="amount_eur must be greater than 0")
        if method not in {"bank_transfer", "cash", "card", "other"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payment method")

        statement = self.get_statement_for_admin(condominium_id=condominium_id, statement_id=statement_id)
        old_status = statement.payment_status
        if statement.payment_status == "waived":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot add payments to waived statements")

        payment = BillingPayment(
            statement_id=statement.id,
            amount_eur=amount_eur.quantize(TWO_DP, rounding=ROUND_HALF_UP),
            method=method,
            transaction_reference=transaction_reference.strip() if transaction_reference else None,
            note=note.strip() if note else None,
            received_at=received_at,
            created_by_app_user_id=created_by_app_user_id,
        )
        self._db.add(payment)
        self._db.flush()

        statement.amount_paid_eur = (Decimal(statement.amount_paid_eur) + Decimal(payment.amount_eur)).quantize(
            TWO_DP, rounding=ROUND_HALF_UP
        )
        self._recompute_amounts_and_status(statement)
        new_status = statement.payment_status

        self._db.add(
            BillingPaymentEvent(
                statement_id=statement.id,
                changed_by_app_user_id=created_by_app_user_id,
                old_status=old_status,
                new_status=new_status,
                note=note.strip() if note else None,
            )
        )
        self._db.commit()
        return payment

    def list_payments(self, *, condominium_id: int, statement_id: int) -> list[BillingPayment]:
        statement = self.get_statement_for_admin(condominium_id=condominium_id, statement_id=statement_id)
        return sorted(statement.payments, key=lambda p: (p.received_at, p.id))

    def waive_statement(
        self,
        *,
        condominium_id: int,
        statement_id: int,
        changed_by_app_user_id: int,
        note: str | None,
    ) -> ResidentBillingStatement:
        statement = self.get_statement_for_admin(condominium_id=condominium_id, statement_id=statement_id)
        old_status = statement.payment_status
        statement.payment_status = "waived"
        statement.amount_due_eur = Decimal("0")
        self._recompute_amounts_and_status(statement)
        self._db.add(
            BillingPaymentEvent(
                statement_id=statement.id,
                changed_by_app_user_id=changed_by_app_user_id,
                old_status=old_status,
                new_status="waived",
                note=note.strip() if note else None,
            )
        )
        self._db.commit()
        return self.get_statement_for_admin(condominium_id=condominium_id, statement_id=statement.id)

    def create_reminder_metadata(
        self,
        *,
        condominium_id: int,
        statement_id: int,
    ) -> ResidentBillingStatement:
        statement = self.get_statement_for_admin(condominium_id=condominium_id, statement_id=statement_id)
        statement.reminder_count = int(statement.reminder_count or 0) + 1
        statement.last_reminder_at = datetime.now(tz=UTC)
        self._db.commit()
        return self.get_statement_for_admin(condominium_id=condominium_id, statement_id=statement.id)

    def create_email_notification(
        self,
        *,
        statement_id: int,
        recipient_email: str,
        notification_type: str,
        subject: str,
        body_preview: str,
        status: str,
        created_by_app_user_id: int,
        error_message: str | None = None,
        sent_at: datetime | None = None,
        retry_of_notification_id: int | None = None,
    ) -> BillingEmailNotification:
        notification = BillingEmailNotification(
            statement_id=statement_id,
            recipient_email=recipient_email,
            notification_type=notification_type,
            subject=subject,
            body_preview=body_preview,
            status=status,
            error_message=error_message,
            sent_at=sent_at,
            retry_of_notification_id=retry_of_notification_id,
            created_by_app_user_id=created_by_app_user_id,
        )
        self._db.add(notification)
        self._db.commit()
        self._db.refresh(notification)
        return notification

    def create_import_job(
        self,
        *,
        condominium_id: int,
        filename: str,
        created_by_app_user_id: int,
    ) -> BillingPaymentImportJob:
        job = BillingPaymentImportJob(
            condominium_id=condominium_id,
            filename=filename,
            status="pending",
            created_by_app_user_id=created_by_app_user_id,
        )
        self._db.add(job)
        self._db.commit()
        self._db.refresh(job)
        return job

    def create_import_job_row(
        self,
        *,
        import_job_id: int,
        row_number: int,
        raw_payment_reference: str | None,
        raw_statement_number: str | None,
        amount_eur: Decimal | None,
        received_at: datetime | None,
        transaction_reference: str | None,
        method: str | None,
        status: str,
        matched_statement_id: int | None = None,
        unmatched_payment_id: int | None = None,
        error_message: str | None = None,
    ) -> BillingPaymentImportRow:
        row = BillingPaymentImportRow(
            import_job_id=import_job_id,
            row_number=row_number,
            raw_payment_reference=raw_payment_reference,
            raw_statement_number=raw_statement_number,
            amount_eur=amount_eur.quantize(TWO_DP, rounding=ROUND_HALF_UP) if amount_eur is not None else None,
            received_at=received_at,
            transaction_reference=transaction_reference,
            method=method,
            status=status,
            matched_statement_id=matched_statement_id,
            unmatched_payment_id=unmatched_payment_id,
            error_message=error_message,
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def finalize_import_job(
        self,
        *,
        condominium_id: int,
        job_id: int,
        status: str,
        rows_total: int,
        rows_processed: int,
        progress_percent: int,
        rows_matched: int,
        rows_unmatched: int,
        rows_duplicate: int,
        rows_failed: int,
        error_message: str | None = None,
    ) -> BillingPaymentImportJob:
        job = self.get_import_job_for_admin(condominium_id=condominium_id, job_id=job_id)
        job.status = status
        job.rows_total = rows_total
        job.rows_processed = rows_processed
        job.progress_percent = progress_percent
        job.rows_matched = rows_matched
        job.rows_unmatched = rows_unmatched
        job.rows_duplicate = rows_duplicate
        job.rows_failed = rows_failed
        job.error_message = error_message
        if status in {"completed", "failed"}:
            job.completed_at = datetime.now(tz=UTC)
        self._db.commit()
        return self.get_import_job_for_admin(condominium_id=condominium_id, job_id=job_id)

    def update_import_job_processing(
        self,
        *,
        condominium_id: int,
        job_id: int,
        rows_total: int,
    ) -> BillingPaymentImportJob:
        job = self._db.get(BillingPaymentImportJob, job_id)
        if job is None or job.condominium_id != condominium_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import job not found")
        job.status = "processing"
        job.rows_total = rows_total
        job.rows_processed = 0
        job.progress_percent = 0
        job.error_message = None
        job.completed_at = None
        self._db.commit()
        return job

    def update_import_job_progress(
        self,
        *,
        condominium_id: int,
        job_id: int,
        rows_processed: int,
    ) -> None:
        job = self._db.get(BillingPaymentImportJob, job_id)
        if job is None or job.condominium_id != condominium_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import job not found")
        job.rows_processed = rows_processed
        if int(job.rows_total or 0) > 0:
            job.progress_percent = min(100, int((rows_processed / int(job.rows_total)) * 100))
        else:
            job.progress_percent = 0
        self._db.commit()

    def add_unmatched_payment(
        self,
        *,
        condominium_id: int,
        raw_reference: str | None,
        amount_eur: Decimal,
        received_at: datetime,
        transaction_reference: str | None,
        method: str | None,
        note: str | None,
        status: str = "unmatched",
        matched_statement_id: int | None = None,
    ) -> BillingUnmatchedPayment:
        unmatched = BillingUnmatchedPayment(
            condominium_id=condominium_id,
            raw_reference=raw_reference,
            amount_eur=amount_eur.quantize(TWO_DP, rounding=ROUND_HALF_UP),
            received_at=received_at,
            transaction_reference=transaction_reference,
            method=method,
            note=note,
            status=status,
            matched_statement_id=matched_statement_id,
        )
        self._db.add(unmatched)
        self._db.commit()
        self._db.refresh(unmatched)
        return unmatched

    def list_import_jobs(self, *, condominium_id: int) -> list[BillingPaymentImportJob]:
        return list(
            self._db.scalars(
            select(BillingPaymentImportJob)
            .options(joinedload(BillingPaymentImportJob.created_by_user))
            .where(BillingPaymentImportJob.condominium_id == condominium_id)
            .order_by(BillingPaymentImportJob.created_at.desc(), BillingPaymentImportJob.id.desc())
            ).all()
        )

    def list_unmatched_payments(
        self,
        *,
        condominium_id: int,
        received_from_date: datetime | None = None,
        received_to_date: datetime | None = None,
        statuses: Sequence[str] | None = ("unmatched",),
    ) -> list[BillingUnmatchedPayment]:
        query = select(BillingUnmatchedPayment).where(BillingUnmatchedPayment.condominium_id == condominium_id)
        if received_from_date is not None:
            query = query.where(BillingUnmatchedPayment.received_at >= received_from_date)
        if received_to_date is not None:
            query = query.where(BillingUnmatchedPayment.received_at <= received_to_date)
        if statuses:
            query = query.where(BillingUnmatchedPayment.status.in_(list(statuses)))
        return list(
            self._db.scalars(query.order_by(BillingUnmatchedPayment.received_at.desc(), BillingUnmatchedPayment.id.desc())).all()
        )

    def match_unmatched_payment(
        self,
        *,
        condominium_id: int,
        unmatched_payment_id: int,
        statement_id: int,
        created_by_app_user_id: int,
    ) -> BillingUnmatchedPayment:
        unmatched = self.get_unmatched_payment_for_admin(condominium_id=condominium_id, unmatched_payment_id=unmatched_payment_id)
        statement = self.get_statement_for_admin(condominium_id=condominium_id, statement_id=statement_id)
        self.add_payment(
            condominium_id=condominium_id,
            statement_id=statement.id,
            created_by_app_user_id=created_by_app_user_id,
            amount_eur=Decimal(unmatched.amount_eur),
            method=unmatched.method or "other",
            transaction_reference=unmatched.transaction_reference,
            note=unmatched.note,
            received_at=unmatched.received_at,
        )
        unmatched.status = "matched"
        unmatched.matched_statement_id = statement.id
        self._db.commit()
        return unmatched

    def ignore_unmatched_payment(self, *, condominium_id: int, unmatched_payment_id: int, note: str | None = None) -> BillingUnmatchedPayment:
        unmatched = self.get_unmatched_payment_for_admin(condominium_id=condominium_id, unmatched_payment_id=unmatched_payment_id)
        unmatched.status = "ignored"
        if note:
            unmatched.note = note
        self._db.commit()
        return unmatched

    def get_or_create_reminder_rule(self, *, condominium_id: int) -> BillingReminderRule:
        existing = self._db.scalar(select(BillingReminderRule).where(BillingReminderRule.condominium_id == condominium_id))
        if existing is not None:
            return existing
        rule = BillingReminderRule(condominium_id=condominium_id)
        self._db.add(rule)
        self._db.commit()
        self._db.refresh(rule)
        return rule

    def update_reminder_rule(
        self,
        *,
        condominium_id: int,
        enabled: bool,
        days_after_period_close: int,
        repeat_every_days: int,
        max_reminders: int,
        min_amount_due_eur: Decimal,
    ) -> BillingReminderRule:
        rule = self.get_or_create_reminder_rule(condominium_id=condominium_id)
        rule.enabled = 1 if enabled else 0
        rule.days_after_period_close = int(days_after_period_close)
        rule.repeat_every_days = int(repeat_every_days)
        rule.max_reminders = int(max_reminders)
        rule.min_amount_due_eur = min_amount_due_eur.quantize(TWO_DP, rounding=ROUND_HALF_UP)
        self._db.commit()
        self._db.refresh(rule)
        return rule

    def reminder_candidates(self, *, condominium_id: int, now: datetime) -> list[ResidentBillingStatement]:
        rule = self.get_or_create_reminder_rule(condominium_id=condominium_id)
        if not bool(rule.enabled):
            return []
        if int(rule.max_reminders) <= 0:
            return []

        query = (
            select(ResidentBillingStatement)
            .join(ResidentBillingStatement.billing_period)
            .options(
                joinedload(ResidentBillingStatement.billing_period),
                joinedload(ResidentBillingStatement.resident),
            )
            .where(BillingPeriod.condominium_id == condominium_id)
            .where(ResidentBillingStatement.payment_status.in_(["unpaid", "partially_paid"]))
            .where(ResidentBillingStatement.amount_due_eur >= rule.min_amount_due_eur)
            .where(BillingPeriod.closed_at.is_not(None))
            .order_by(ResidentBillingStatement.id.asc())
        )
        rows = self._db.execute(query).unique().scalars().all()

        eligible: list[ResidentBillingStatement] = []
        for statement in rows:
            closed_at = statement.billing_period.closed_at
            if closed_at is None:
                continue
            closed_at_utc = _normalize_utc(closed_at)
            if closed_at_utc is None:
                continue
            eligible_after = closed_at_utc + timedelta(days=int(rule.days_after_period_close))
            now_utc = _normalize_utc(now)
            if now_utc is None:
                continue
            if now_utc < eligible_after:
                continue
            if int(statement.reminder_count or 0) >= int(rule.max_reminders):
                continue
            if statement.last_reminder_at is not None:
                last = _normalize_utc(statement.last_reminder_at)
                if last is not None and now_utc < last + timedelta(days=int(rule.repeat_every_days)):
                    continue
            eligible.append(statement)
        return eligible

    def _is_blank_csv_row(self, row: dict[str, str | None]) -> bool:
        return all(not (value or "").strip() for value in row.values())

    def _parse_csv_datetime(self, raw_value: str) -> datetime:
        normalized = raw_value.replace("Z", "+00:00")
        parsed = _normalize_utc(datetime.fromisoformat(normalized))
        if parsed is None:
            raise ValueError("received_at is required")
        return parsed

    def import_payments_csv(
        self,
        *,
        condominium_id: int,
        created_by_app_user_id: int,
        csv_text: str,
        filename: str = "payments.csv",
    ) -> dict[str, object]:
        job = self.create_import_job(
            condominium_id=condominium_id,
            filename=filename,
            created_by_app_user_id=created_by_app_user_id,
        )
        return self.process_import_job(
            condominium_id=condominium_id,
            job_id=job.id,
            created_by_app_user_id=created_by_app_user_id,
            csv_text=csv_text,
        )

    def process_import_job(
        self,
        *,
        condominium_id: int,
        job_id: int,
        created_by_app_user_id: int,
        csv_text: str,
    ) -> dict[str, object]:
        total_reader = csv.DictReader(io.StringIO(csv_text))
        rows_total = sum(1 for row in total_reader if not self._is_blank_csv_row(row))
        self.update_import_job_processing(condominium_id=condominium_id, job_id=job_id, rows_total=rows_total)

        reader = csv.DictReader(io.StringIO(csv_text))
        imported_rows: list[BillingPaymentImportRow] = []
        unmatched_rows: list[BillingUnmatchedPayment] = []
        matched_count = 0
        duplicate_count = 0
        failed_count = 0
        rows_processed = 0
        seen_transaction_refs: set[str] = set()

        try:
            for row_number, row in enumerate(reader, start=2):
                if self._is_blank_csv_row(row):
                    continue
                rows_processed += 1
                if rows_total:
                    self.update_import_job_progress(
                        condominium_id=condominium_id,
                        job_id=job_id,
                        rows_processed=rows_processed,
                    )
                payment_reference = (row.get("payment_reference") or "").strip() or None
                statement_number = (row.get("statement_number") or "").strip() or None
                amount_raw = (row.get("amount_eur") or "").strip()
                received_at_raw = (row.get("received_at") or "").strip()
                transaction_reference = (row.get("transaction_reference") or "").strip() or None
                method = (row.get("method") or "bank_transfer").strip() or "bank_transfer"
                note = (row.get("note") or "").strip() or None

                try:
                    if not amount_raw:
                        raise ValueError("amount_eur is required")
                    if not received_at_raw:
                        raise ValueError("received_at is required")
                    if payment_reference is None and statement_number is None:
                        raise ValueError("payment_reference or statement_number is required")
                    amount = Decimal(amount_raw)
                    received_at = self._parse_csv_datetime(received_at_raw)
                except Exception as exc:
                    parsed_amount: Decimal | None = None
                    if amount_raw:
                        try:
                            parsed_amount = Decimal(amount_raw)
                        except Exception:
                            parsed_amount = None
                    failed_count += 1
                    imported_rows.append(
                        self.create_import_job_row(
                            import_job_id=job_id,
                            row_number=row_number,
                            raw_payment_reference=payment_reference,
                            raw_statement_number=statement_number,
                            amount_eur=parsed_amount,
                            received_at=None,
                            transaction_reference=transaction_reference,
                            method=method,
                            status="failed",
                            error_message=str(exc),
                        )
                    )
                    continue

                if transaction_reference and (
                    transaction_reference in seen_transaction_refs
                    or self._has_duplicate_transaction_reference(
                        condominium_id=condominium_id,
                        transaction_reference=transaction_reference,
                    )
                ):
                    duplicate_count += 1
                    imported_rows.append(
                        self.create_import_job_row(
                            import_job_id=job_id,
                            row_number=row_number,
                            raw_payment_reference=payment_reference,
                            raw_statement_number=statement_number,
                            amount_eur=amount,
                            received_at=received_at,
                            transaction_reference=transaction_reference,
                            method=method,
                            status="duplicate",
                            error_message="Duplicate transaction_reference ignored",
                        )
                    )
                    continue

                statement = self._match_statement(
                    condominium_id=condominium_id,
                    payment_reference=payment_reference,
                    statement_number=statement_number,
                )
                if statement is None:
                    unmatched = self.add_unmatched_payment(
                        condominium_id=condominium_id,
                        raw_reference=payment_reference or statement_number,
                        amount_eur=amount,
                        received_at=received_at,
                        transaction_reference=transaction_reference,
                        method=method,
                        note=note,
                    )
                    unmatched_rows.append(unmatched)
                    imported_rows.append(
                        self.create_import_job_row(
                            import_job_id=job_id,
                            row_number=row_number,
                            raw_payment_reference=payment_reference,
                            raw_statement_number=statement_number,
                            amount_eur=amount,
                            received_at=received_at,
                            transaction_reference=transaction_reference,
                            method=method,
                            status="unmatched",
                            unmatched_payment_id=unmatched.id,
                        )
                    )
                    if transaction_reference:
                        seen_transaction_refs.add(transaction_reference)
                    continue

                self.add_payment(
                    condominium_id=condominium_id,
                    statement_id=statement.id,
                    created_by_app_user_id=created_by_app_user_id,
                    amount_eur=amount,
                    method=method,
                    transaction_reference=transaction_reference,
                    note=note,
                    received_at=received_at,
                )
                matched_count += 1
                imported_rows.append(
                    self.create_import_job_row(
                        import_job_id=job_id,
                        row_number=row_number,
                        raw_payment_reference=payment_reference,
                        raw_statement_number=statement_number,
                        amount_eur=amount,
                        received_at=received_at,
                        transaction_reference=transaction_reference,
                        method=method,
                        status="matched",
                        matched_statement_id=statement.id,
                    )
                )
                if transaction_reference:
                    seen_transaction_refs.add(transaction_reference)
        except Exception as exc:
            progress_percent = min(100, int((rows_processed / rows_total) * 100)) if rows_total else 0
            job = self.finalize_import_job(
                condominium_id=condominium_id,
                job_id=job_id,
                status="failed",
                rows_total=rows_total,
                rows_processed=rows_processed,
                progress_percent=progress_percent,
                rows_matched=matched_count,
                rows_unmatched=len(unmatched_rows),
                rows_duplicate=duplicate_count,
                rows_failed=failed_count,
                error_message=str(exc),
            )
            raise

        job = self.finalize_import_job(
            condominium_id=condominium_id,
            job_id=job_id,
            status="completed",
            rows_total=rows_total,
            rows_processed=rows_total,
            progress_percent=100 if rows_total else 0,
            rows_matched=matched_count,
            rows_unmatched=len(unmatched_rows),
            rows_duplicate=duplicate_count,
            rows_failed=failed_count,
        )
        return {
            "job": job,
            "imported_count": matched_count,
            "duplicate_count": duplicate_count,
            "unmatched_count": len(unmatched_rows),
            "failed_count": failed_count,
            "unmatched_payments": unmatched_rows,
            "rows": imported_rows,
        }

    def reconciliation_rows(
        self,
        *,
        condominium_id: int,
        period_id: int | None,
        resident_id: int | None,
        payment_status: str | None,
        from_date: datetime | None,
        to_date: datetime | None,
        received_from_date: datetime | None,
        received_to_date: datetime | None,
    ) -> list[ResidentBillingStatement]:
        query = (
            select(ResidentBillingStatement)
            .join(ResidentBillingStatement.billing_period)
            .options(
                joinedload(ResidentBillingStatement.billing_period),
                joinedload(ResidentBillingStatement.resident),
                joinedload(ResidentBillingStatement.payments).joinedload(BillingPayment.created_by_user),
            )
            .where(BillingPeriod.condominium_id == condominium_id)
        )
        if period_id is not None:
            query = query.where(ResidentBillingStatement.billing_period_id == period_id)
        if resident_id is not None:
            query = query.where(ResidentBillingStatement.resident_app_user_id == resident_id)
        if payment_status is not None:
            query = query.where(ResidentBillingStatement.payment_status == payment_status)
        if from_date is not None:
            query = query.where(ResidentBillingStatement.generated_at >= from_date)
        if to_date is not None:
            query = query.where(ResidentBillingStatement.generated_at <= to_date)

        rows = list(
            self._db.execute(query.order_by(ResidentBillingStatement.generated_at.desc(), ResidentBillingStatement.id.desc())).unique().scalars().all()
        )
        if received_from_date is None and received_to_date is None:
            return rows
        normalized_from = _normalize_utc(received_from_date)
        normalized_to = _normalize_utc(received_to_date)
        filtered: list[ResidentBillingStatement] = []
        for statement in rows:
            matching = [
                payment
                for payment in statement.payments
                if (
                    normalized_from is None
                    or ((_normalize_utc(payment.received_at)) is not None and _normalize_utc(payment.received_at) >= normalized_from)
                )
                and (
                    normalized_to is None
                    or ((_normalize_utc(payment.received_at)) is not None and _normalize_utc(payment.received_at) <= normalized_to)
                )
            ]
            if matching:
                filtered.append(statement)
        return filtered

    def settlement_summary(self, *, condominium_id: int) -> dict[str, float | int]:
        statements = self._db.scalars(
            select(ResidentBillingStatement)
            .join(ResidentBillingStatement.billing_period)
            .where(BillingPeriod.condominium_id == condominium_id)
        ).all()
        periods = self._db.scalars(
            select(BillingPeriod).where(BillingPeriod.condominium_id == condominium_id)
        ).all()

        total_billed = sum(float(statement.amount_eur) for statement in statements)
        paid = sum(float(statement.amount_eur) for statement in statements if statement.payment_status == "paid")
        unpaid = sum(float(statement.amount_eur) for statement in statements if statement.payment_status == "unpaid")
        waived = sum(float(statement.amount_eur) for statement in statements if statement.payment_status == "waived")
        partially_paid = sum(float(statement.amount_eur) for statement in statements if statement.payment_status == "partially_paid")
        collection_rate = round((paid / total_billed) * 100.0, 2) if total_billed else 0.0
        open_periods = sum(1 for period in periods if period.status != "closed")
        closed_periods = sum(1 for period in periods if period.status == "closed")
        return {
            "total_billed_eur": round(total_billed, 2),
            "paid_eur": round(paid, 2),
            "unpaid_eur": round(unpaid, 2),
            "waived_eur": round(waived, 2),
            "partially_paid_eur": round(partially_paid, 2),
            "collection_rate": collection_rate,
            "open_periods": open_periods,
            "closed_periods": closed_periods,
        }
