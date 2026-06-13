"""Resident invitation tokens

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resident_invitation_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "app_user_id",
            sa.Integer(),
            sa.ForeignKey("app_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_admin_id",
            sa.Integer(),
            sa.ForeignKey("app_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("token_hash", name="uq_resident_invitation_tokens_token_hash"),
    )
    op.create_index(
        "ix_resident_invitation_tokens_app_user_id",
        "resident_invitation_tokens",
        ["app_user_id"],
    )
    op.create_index(
        "ix_resident_invitation_tokens_created_by_admin_id",
        "resident_invitation_tokens",
        ["created_by_admin_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_resident_invitation_tokens_created_by_admin_id", table_name="resident_invitation_tokens")
    op.drop_index("ix_resident_invitation_tokens_app_user_id", table_name="resident_invitation_tokens")
    op.drop_table("resident_invitation_tokens")
