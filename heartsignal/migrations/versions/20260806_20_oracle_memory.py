"""Add explicit-consent encrypted oracle memory.

Revision ID: 20260806_20
Revises: 20260806_19
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_20"
down_revision: str | None = "20260806_19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oracle_memory_consents",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("consent_version", sa.String(length=64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('granted','revoked')",
            name="ck_oracle_memory_consents_status",
        ),
        sa.CheckConstraint(
            "(status = 'granted' AND accepted_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL)",
            name="ck_oracle_memory_consents_state",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "oracle_memory_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("confidence_milli", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_reading_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_persona_code", sa.String(length=64), nullable=True),
        sa.Column("extraction_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('user_preference','personal_goal','relationship_context',"
            "'recurring_theme','birth_profile','oracle_preference')",
            name="ck_oracle_memory_items_kind",
        ),
        sa.CheckConstraint(
            "status IN ('active','deleted')",
            name="ck_oracle_memory_items_status",
        ),
        sa.CheckConstraint(
            "confidence_milli BETWEEN 1 AND 1000",
            name="ck_oracle_memory_items_confidence",
        ),
        sa.CheckConstraint(
            "source_type IN ('user_explicit','reading_derived','profile_imported')",
            name="ck_oracle_memory_items_source_type",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND deleted_at IS NULL) OR "
            "(status = 'deleted' AND deleted_at IS NOT NULL)",
            name="ck_oracle_memory_items_state",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_reading_id"],
            ["readings.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_oracle_memory_items_user_id",
        "oracle_memory_items",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_oracle_memory_items_source_reading_id",
        "oracle_memory_items",
        ["source_reading_id"],
        unique=False,
    )
    op.create_index(
        "ix_oracle_memory_items_user_status_created",
        "oracle_memory_items",
        ["user_id", "status", "created_at"],
        unique=False,
    )

    op.create_table(
        "oracle_memory_private_content",
        sa.Column("memory_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("value_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("value_format_version", sa.Integer(), nullable=True),
        sa.Column("content_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(value_ciphertext IS NOT NULL AND value_format_version IS NOT NULL "
            "AND value_format_version > 0 AND content_deleted_at IS NULL) OR "
            "(value_ciphertext IS NULL AND value_format_version IS NULL "
            "AND content_deleted_at IS NOT NULL)",
            name="ck_oracle_memory_private_content_state",
        ),
        sa.ForeignKeyConstraint(
            ["memory_item_id"],
            ["oracle_memory_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("memory_item_id"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    memory_rows = connection.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM oracle_memory_items) + "
            "(SELECT count(*) FROM oracle_memory_consents)"
        )
    ).scalar_one()
    if memory_rows:
        raise RuntimeError("downgrade refused: oracle memory data exists")

    op.drop_table("oracle_memory_private_content")
    op.drop_index(
        "ix_oracle_memory_items_user_status_created",
        table_name="oracle_memory_items",
    )
    op.drop_index(
        "ix_oracle_memory_items_source_reading_id",
        table_name="oracle_memory_items",
    )
    op.drop_index("ix_oracle_memory_items_user_id", table_name="oracle_memory_items")
    op.drop_table("oracle_memory_items")
    op.drop_table("oracle_memory_consents")
