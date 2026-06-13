from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from condocharge.db.base import Base


class BillingPeriod(Base):
    __tablename__ = "billing_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condominium_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("condominiums.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="draft")
    energy_price_eur_per_kwh_snapshot: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        server_default="0.30",
    )
    unassigned_sessions_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unassigned_energy_kwh: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, server_default="0")
    unassigned_amount_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    statements: Mapped[list["ResidentBillingStatement"]] = relationship(
        back_populates="billing_period",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    condominium: Mapped[object] = relationship("Condominium", back_populates="billing_periods")


class ResidentBillingStatement(Base):
    __tablename__ = "resident_billing_statements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    billing_period_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("billing_periods.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resident_app_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sessions_count: Mapped[int] = mapped_column(Integer, nullable=False)
    energy_kwh: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    amount_paid_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    amount_due_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    statement_number: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    payment_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="unpaid")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    billing_period: Mapped[BillingPeriod] = relationship(back_populates="statements")
    resident: Mapped[object] = relationship("AppUser", back_populates="billing_statements")
    session_links: Mapped[list["ResidentBillingStatementSession"]] = relationship(
        back_populates="statement",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    payment_events: Mapped[list["BillingPaymentEvent"]] = relationship(
        back_populates="statement",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    payments: Mapped[list["BillingPayment"]] = relationship(
        back_populates="statement",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    email_notifications: Mapped[list["BillingEmailNotification"]] = relationship(
        back_populates="statement",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    import_rows: Mapped[list["BillingPaymentImportRow"]] = relationship(
        back_populates="matched_statement",
        passive_deletes=True,
    )


class ResidentBillingStatementSession(Base):
    __tablename__ = "resident_billing_statement_sessions"
    __table_args__ = (
        UniqueConstraint("statement_id", "charging_session_id", name="uq_statement_session"),
        UniqueConstraint("charging_session_id", name="uq_billed_charging_session"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    statement_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("resident_billing_statements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    charging_session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("charging_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    statement: Mapped[ResidentBillingStatement] = relationship(back_populates="session_links")
    charging_session: Mapped[object] = relationship("ChargingSession")


class BillingPaymentEvent(Base):
    __tablename__ = "billing_payment_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    statement_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("resident_billing_statements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    changed_by_app_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    old_status: Mapped[str] = mapped_column(String(32), nullable=False)
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    statement: Mapped[ResidentBillingStatement] = relationship(back_populates="payment_events")
    changed_by_user: Mapped[object] = relationship("AppUser")


class BillingPayment(Base):
    __tablename__ = "billing_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    statement_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("resident_billing_statements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    transaction_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_app_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    statement: Mapped[ResidentBillingStatement] = relationship(back_populates="payments")
    created_by_user: Mapped[object] = relationship("AppUser")


class BillingEmailNotification(Base):
    __tablename__ = "billing_email_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    statement_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("resident_billing_statements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body_preview: Mapped[str] = mapped_column(String(4000), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_of_notification_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("billing_email_notifications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_app_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    statement: Mapped[ResidentBillingStatement] = relationship(back_populates="email_notifications")
    created_by_user: Mapped[object] = relationship("AppUser")
    retry_of_notification: Mapped["BillingEmailNotification | None"] = relationship(remote_side="BillingEmailNotification.id")


class BillingUnmatchedPayment(Base):
    __tablename__ = "billing_unmatched_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condominium_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("condominiums.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raw_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    transaction_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="unmatched")
    matched_statement_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("resident_billing_statements.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    condominium: Mapped[object] = relationship("Condominium")
    matched_statement: Mapped[object] = relationship("ResidentBillingStatement")
    import_rows: Mapped[list["BillingPaymentImportRow"]] = relationship(
        back_populates="unmatched_payment",
        passive_deletes=True,
    )


class BillingPaymentImportJob(Base):
    __tablename__ = "billing_payment_import_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condominium_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("condominiums.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_processed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_matched: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_unmatched: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_duplicate: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by_app_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("app_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    condominium: Mapped[object] = relationship("Condominium")
    created_by_user: Mapped[object] = relationship("AppUser")
    rows: Mapped[list["BillingPaymentImportRow"]] = relationship(
        back_populates="import_job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class BillingPaymentImportRow(Base):
    __tablename__ = "billing_payment_import_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    import_job_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("billing_payment_import_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_statement_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transaction_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    matched_statement_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("resident_billing_statements.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    unmatched_payment_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("billing_unmatched_payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    import_job: Mapped[BillingPaymentImportJob] = relationship(back_populates="rows")
    matched_statement: Mapped[ResidentBillingStatement | None] = relationship(back_populates="import_rows")
    unmatched_payment: Mapped[BillingUnmatchedPayment | None] = relationship(back_populates="import_rows")


class BillingReminderRule(Base):
    __tablename__ = "billing_reminder_rules"
    __table_args__ = (UniqueConstraint("condominium_id", name="uq_billing_reminder_rules_condominium_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    condominium_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("condominiums.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    days_after_period_close: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    repeat_every_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="14")
    max_reminders: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    min_amount_due_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    condominium: Mapped[object] = relationship("Condominium")
