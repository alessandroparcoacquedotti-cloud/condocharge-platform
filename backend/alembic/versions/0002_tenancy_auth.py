"""Condominiums and app users, plus tenant scoping

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-09
"""

from __future__ import annotations

import base64
import hashlib
import os

from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _hash_password(password: str) -> str:
    iterations = 260_000
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "condominiums",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("name", name="uq_condominiums_name"),
    )

    op.create_table(
        "app_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("condominium_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["condominium_id"], ["condominiums.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("condominium_id", "username", name="uq_app_users_condo_username"),
    )
    op.create_index("ix_app_users_condominium_id", "app_users", ["condominium_id"])

    with op.batch_alter_table("charging_stations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "condominium_id",
                sa.Integer(),
                sa.ForeignKey(
                    "condominiums.id",
                    name="fk_charging_stations_condominium_id_condominiums",
                    ondelete="CASCADE",
                ),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.create_index("ix_charging_stations_condominium_id", ["condominium_id"])

    with op.batch_alter_table("rfid_users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "condominium_id",
                sa.Integer(),
                sa.ForeignKey(
                    "condominiums.id",
                    name="fk_rfid_users_condominium_id_condominiums",
                    ondelete="CASCADE",
                ),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.create_index("ix_rfid_users_condominium_id", ["condominium_id"])

    with op.batch_alter_table("charging_sessions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "condominium_id",
                sa.Integer(),
                sa.ForeignKey(
                    "condominiums.id",
                    name="fk_charging_sessions_condominium_id_condominiums",
                    ondelete="CASCADE",
                ),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.create_index("ix_charging_sessions_condominium_id", ["condominium_id"])

    bind.execute(
        sa.text(
            "INSERT INTO condominiums (id, name, created_at, updated_at) "
            "VALUES (1, :name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"name": "Default Condominium"},
    )
    op.execute(sa.text("UPDATE charging_stations SET condominium_id = 1 WHERE condominium_id IS NULL"))
    op.execute(sa.text("UPDATE rfid_users SET condominium_id = 1 WHERE condominium_id IS NULL"))
    op.execute(sa.text("UPDATE charging_sessions SET condominium_id = 1 WHERE condominium_id IS NULL"))

    bind.execute(
        sa.text(
            "INSERT INTO app_users (condominium_id, username, password_hash, role, is_active, created_at, updated_at) "
            "VALUES (1, :username, :password_hash, :role, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"username": "admin", "password_hash": _hash_password("admin"), "role": "admin"},
    )


def downgrade() -> None:
    op.drop_index("ix_charging_sessions_condominium_id", table_name="charging_sessions")
    op.drop_index("ix_rfid_users_condominium_id", table_name="rfid_users")
    op.drop_index("ix_charging_stations_condominium_id", table_name="charging_stations")
    op.drop_index("ix_app_users_condominium_id", table_name="app_users")

    op.drop_column("charging_sessions", "condominium_id")
    op.drop_column("rfid_users", "condominium_id")
    op.drop_column("charging_stations", "condominium_id")

    op.drop_table("app_users")
    op.drop_table("condominiums")
