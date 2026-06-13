"""App user profile fields and password flags

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-11
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_users", sa.Column("first_name", sa.String(length=128), nullable=True))
    op.add_column("app_users", sa.Column("last_name", sa.String(length=128), nullable=True))
    op.add_column("app_users", sa.Column("apartment_or_unit", sa.String(length=128), nullable=True))
    op.add_column("app_users", sa.Column("phone_number", sa.String(length=64), nullable=True))
    op.add_column("app_users", sa.Column("must_change_password", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("app_users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("app_users", "last_login_at")
    op.drop_column("app_users", "must_change_password")
    op.drop_column("app_users", "phone_number")
    op.drop_column("app_users", "apartment_or_unit")
    op.drop_column("app_users", "last_name")
    op.drop_column("app_users", "first_name")

