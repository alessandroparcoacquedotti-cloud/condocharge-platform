"""Billing and settlement MVP

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_periods",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("condominium_id", sa.Integer(), sa.ForeignKey("condominiums.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("energy_price_eur_per_kwh_snapshot", sa.Numeric(10, 4), nullable=False, server_default="0.30"),
        sa.Column("unassigned_sessions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unassigned_energy_kwh", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("unassigned_amount_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_billing_periods_condominium_id", "billing_periods", ["condominium_id"])

    op.create_table(
        "resident_billing_statements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("billing_period_id", sa.Integer(), sa.ForeignKey("billing_periods.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resident_app_user_id", sa.Integer(), sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sessions_count", sa.Integer(), nullable=False),
        sa.Column("energy_kwh", sa.Numeric(12, 3), nullable=False),
        sa.Column("amount_eur", sa.Numeric(12, 2), nullable=False),
        sa.Column("payment_status", sa.String(length=32), nullable=False, server_default="unpaid"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_resident_billing_statements_billing_period_id", "resident_billing_statements", ["billing_period_id"])
    op.create_index("ix_resident_billing_statements_resident_app_user_id", "resident_billing_statements", ["resident_app_user_id"])

    op.create_table(
        "resident_billing_statement_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "statement_id",
            sa.Integer(),
            sa.ForeignKey("resident_billing_statements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "charging_session_id",
            sa.Integer(),
            sa.ForeignKey("charging_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("statement_id", "charging_session_id", name="uq_statement_session"),
        sa.UniqueConstraint("charging_session_id", name="uq_billed_charging_session"),
    )
    op.create_index(
        "ix_resident_billing_statement_sessions_statement_id",
        "resident_billing_statement_sessions",
        ["statement_id"],
    )
    op.create_index(
        "ix_resident_billing_statement_sessions_charging_session_id",
        "resident_billing_statement_sessions",
        ["charging_session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_resident_billing_statement_sessions_charging_session_id", table_name="resident_billing_statement_sessions")
    op.drop_index("ix_resident_billing_statement_sessions_statement_id", table_name="resident_billing_statement_sessions")
    op.drop_table("resident_billing_statement_sessions")

    op.drop_index("ix_resident_billing_statements_resident_app_user_id", table_name="resident_billing_statements")
    op.drop_index("ix_resident_billing_statements_billing_period_id", table_name="resident_billing_statements")
    op.drop_table("resident_billing_statements")

    op.drop_index("ix_billing_periods_condominium_id", table_name="billing_periods")
    op.drop_table("billing_periods")

