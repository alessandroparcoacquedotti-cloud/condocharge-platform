"""Payment operations hardening

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_payment_import_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "condominium_id",
            sa.Integer(),
            sa.ForeignKey("condominiums.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("rows_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_matched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_unmatched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_duplicate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_by_app_user_id",
            sa.Integer(),
            sa.ForeignKey("app_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_billing_payment_import_jobs_condominium_id", "billing_payment_import_jobs", ["condominium_id"])
    op.create_index(
        "ix_billing_payment_import_jobs_created_by_app_user_id",
        "billing_payment_import_jobs",
        ["created_by_app_user_id"],
    )

    op.create_table(
        "billing_payment_import_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "import_job_id",
            sa.Integer(),
            sa.ForeignKey("billing_payment_import_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_payment_reference", sa.String(length=255), nullable=True),
        sa.Column("raw_statement_number", sa.String(length=255), nullable=True),
        sa.Column("amount_eur", sa.Numeric(12, 2), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transaction_reference", sa.String(length=255), nullable=True),
        sa.Column("method", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "matched_statement_id",
            sa.Integer(),
            sa.ForeignKey("resident_billing_statements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "unmatched_payment_id",
            sa.Integer(),
            sa.ForeignKey("billing_unmatched_payments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_billing_payment_import_rows_import_job_id", "billing_payment_import_rows", ["import_job_id"])
    op.create_index(
        "ix_billing_payment_import_rows_matched_statement_id",
        "billing_payment_import_rows",
        ["matched_statement_id"],
    )
    op.create_index(
        "ix_billing_payment_import_rows_unmatched_payment_id",
        "billing_payment_import_rows",
        ["unmatched_payment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_billing_payment_import_rows_unmatched_payment_id", table_name="billing_payment_import_rows")
    op.drop_index("ix_billing_payment_import_rows_matched_statement_id", table_name="billing_payment_import_rows")
    op.drop_index("ix_billing_payment_import_rows_import_job_id", table_name="billing_payment_import_rows")
    op.drop_table("billing_payment_import_rows")

    op.drop_index("ix_billing_payment_import_jobs_created_by_app_user_id", table_name="billing_payment_import_jobs")
    op.drop_index("ix_billing_payment_import_jobs_condominium_id", table_name="billing_payment_import_jobs")
    op.drop_table("billing_payment_import_jobs")
