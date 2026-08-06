"""Add explicit-consent encrypted birth profiles.

Revision ID: 20260806_24
Revises: 20260806_23
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_24"
down_revision: str | None = "20260806_23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "birth_profile_consents",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("consent_version", sa.String(length=64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('granted','revoked')",
            name="ck_birth_profile_consents_status",
        ),
        sa.CheckConstraint(
            "(status = 'granted' AND accepted_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL)",
            name="ck_birth_profile_consents_state",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "birth_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("profile_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active','deleted')",
            name="ck_birth_profiles_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND deleted_at IS NULL) OR "
            "(status = 'deleted' AND deleted_at IS NOT NULL)",
            name="ck_birth_profiles_state",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_birth_profiles_user_id"),
    )
    op.create_index("ix_birth_profiles_user_id", "birth_profiles", ["user_id"], unique=True)
    op.create_table(
        "birth_profile_private_content",
        sa.Column("birth_profile_id", sa.Uuid(), nullable=False),
        sa.Column("payload_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("payload_format_version", sa.Integer(), nullable=True),
        sa.Column("content_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(payload_ciphertext IS NOT NULL AND payload_format_version IS NOT NULL "
            "AND payload_format_version > 0 AND content_deleted_at IS NULL) OR "
            "(payload_ciphertext IS NULL AND payload_format_version IS NULL "
            "AND content_deleted_at IS NOT NULL)",
            name="ck_birth_profile_private_content_state",
        ),
        sa.ForeignKeyConstraint(
            ["birth_profile_id"],
            ["birth_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("birth_profile_id"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    row_count = connection.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM birth_profile_consents) + "
            "(SELECT count(*) FROM birth_profiles)"
        )
    ).scalar_one()
    if row_count:
        raise RuntimeError("downgrade refused: encrypted birth profile state would be lost")
    op.drop_table("birth_profile_private_content")
    op.drop_index("ix_birth_profiles_user_id", table_name="birth_profiles")
    op.drop_table("birth_profiles")
    op.drop_table("birth_profile_consents")
