"""add independent oracle reading domain

Revision ID: 20260805_17
Revises: 20260805_16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260805_17"
down_revision: str | None = "20260805_16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "personas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_personas_code", "personas", ["code"], unique=True)

    op.create_table(
        "readings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="draft", nullable=False),
        sa.Column("access_level", sa.String(length=16), server_default="none", nullable=False),
        sa.Column("cost_units", sa.Integer(), server_default="0", nullable=False),
        sa.Column("engine_version", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("generation_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
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
            "status IN ('draft','generating','preview_ready','full_ready','failed','deleted')",
            name="ck_readings_status",
        ),
        sa.CheckConstraint(
            "access_level IN ('none','preview','full')",
            name="ck_readings_access_level",
        ),
        sa.CheckConstraint("cost_units >= 0", name="ck_readings_cost_units"),
        sa.CheckConstraint(
            "(status IN ('draft','generating','failed','deleted') AND access_level = 'none') OR "
            "(status = 'preview_ready' AND access_level = 'preview') OR "
            "(status = 'full_ready' AND access_level = 'full')",
            name="ck_readings_status_access",
        ),
        sa.CheckConstraint(
            "(status IN ('preview_ready','full_ready') AND generated_at IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(status = 'failed' AND generated_at IS NULL AND failure_code IS NOT NULL) OR "
            "(status IN ('draft','generating','deleted') AND generated_at IS NULL)",
            name="ck_readings_terminal_state",
        ),
        sa.CheckConstraint(
            "status <> 'deleted' OR deleted_at IS NOT NULL",
            name="ck_readings_deleted_at",
        ),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_readings_user_id", "readings", ["user_id"], unique=False)
    op.create_index("ix_readings_persona_id", "readings", ["persona_id"], unique=False)
    op.create_index(
        "ix_readings_user_created",
        "readings",
        ["user_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "reading_private_content",
        sa.Column("reading_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("context_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("result_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("question_format_version", sa.Integer(), nullable=True),
        sa.Column("context_format_version", sa.Integer(), nullable=True),
        sa.Column("result_format_version", sa.Integer(), nullable=True),
        sa.Column("content_delete_after", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["reading_id"], ["readings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("reading_id"),
    )
    op.create_index(
        "ix_reading_private_content_content_delete_after",
        "reading_private_content",
        ["content_delete_after"],
        unique=False,
    )

    op.create_table(
        "reading_symbols",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reading_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("symbol_id", sa.String(length=64), nullable=False),
        sa.Column("position", sa.String(length=64), nullable=False),
        sa.Column("orientation", sa.String(length=16), server_default="neutral", nullable=False),
        sa.Column("catalog_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_reading_symbols_ordinal"),
        sa.CheckConstraint(
            "orientation IN ('upright','reversed','neutral')",
            name="ck_reading_symbols_orientation",
        ),
        sa.ForeignKeyConstraint(["reading_id"], ["readings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reading_id", "ordinal", name="uq_reading_symbols_ordinal"),
        sa.UniqueConstraint("reading_id", "position", name="uq_reading_symbols_position"),
    )
    op.create_index(
        "ix_reading_symbols_reading_id",
        "reading_symbols",
        ["reading_id"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT count(*) FROM readings")):
        raise RuntimeError("downgrade refused: readings contains user state")
    if bind.scalar(sa.text("SELECT count(*) FROM personas")):
        raise RuntimeError("downgrade refused: personas contains configured state")
    op.drop_index("ix_reading_symbols_reading_id", table_name="reading_symbols")
    op.drop_table("reading_symbols")
    op.drop_index(
        "ix_reading_private_content_content_delete_after",
        table_name="reading_private_content",
    )
    op.drop_table("reading_private_content")
    op.drop_index("ix_readings_user_created", table_name="readings")
    op.drop_index("ix_readings_persona_id", table_name="readings")
    op.drop_index("ix_readings_user_id", table_name="readings")
    op.drop_table("readings")
    op.drop_index("ix_personas_code", table_name="personas")
    op.drop_table("personas")
