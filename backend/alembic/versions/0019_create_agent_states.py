"""Create persisted agent state table

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_states",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("condominium_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("agent_version", sa.String(length=64), nullable=True),
        sa.Column("last_heartbeat_at", sa.String(length=64), nullable=True),
        sa.Column("last_station_update_at", sa.String(length=64), nullable=True),
        sa.Column("last_session_import_at", sa.String(length=64), nullable=True),
        sa.Column("heartbeat_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("polling_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("import_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["condominium_id"], ["condominiums.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("condominium_id", "agent_id", name="uq_agent_states_condo_agent"),
    )
    op.create_index(op.f("ix_agent_states_condominium_id"), "agent_states", ["condominium_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_states_condominium_id"), table_name="agent_states")
    op.drop_table("agent_states")
