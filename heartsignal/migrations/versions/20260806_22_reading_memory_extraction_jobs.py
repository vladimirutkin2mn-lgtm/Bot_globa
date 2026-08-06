"""Add durable completed-reading memory extraction jobs.

Revision ID: 20260806_22
Revises: 20260806_21
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_22"
down_revision: str | None = "20260806_21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reading_memory_extraction_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reading_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_version", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("claim_id", sa.Uuid(), nullable=True),
        sa.Column("claimed_by", sa.String(length=255), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending','claimed','completed','skipped_no_consent',"
            "'skipped_source_unavailable','failed')",
            name="ck_reading_memory_extraction_jobs_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_reading_memory_extraction_jobs_attempt_count",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND claim_id IS NULL AND claimed_by IS NULL "
            "AND claimed_at IS NULL AND lease_until IS NULL AND completed_at IS NULL) OR "
            "(status = 'claimed' AND claim_id IS NOT NULL AND claimed_by IS NOT NULL "
            "AND claimed_at IS NOT NULL AND lease_until IS NOT NULL AND completed_at IS NULL) OR "
            "(status IN ('completed','skipped_no_consent','skipped_source_unavailable','failed') "
            "AND claim_id IS NULL AND lease_until IS NULL AND completed_at IS NOT NULL)",
            name="ck_reading_memory_extraction_jobs_state",
        ),
        sa.ForeignKeyConstraint(
            ["reading_id"],
            ["readings.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reading_id",
            "extraction_version",
            name="uq_reading_memory_extraction_job_version",
        ),
    )
    op.create_index(
        "ix_reading_memory_extraction_jobs_reading_id",
        "reading_memory_extraction_jobs",
        ["reading_id"],
        unique=False,
    )
    op.create_index(
        "ix_reading_memory_extraction_jobs_user_id",
        "reading_memory_extraction_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_reading_memory_extraction_jobs_due",
        "reading_memory_extraction_jobs",
        ["status", "available_at", "lease_until", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT count(*) FROM reading_memory_extraction_jobs")
    ).scalar_one()
    if rows:
        raise RuntimeError("downgrade refused: reading memory extraction jobs would be lost")
    op.drop_index(
        "ix_reading_memory_extraction_jobs_due",
        table_name="reading_memory_extraction_jobs",
    )
    op.drop_index(
        "ix_reading_memory_extraction_jobs_user_id",
        table_name="reading_memory_extraction_jobs",
    )
    op.drop_index(
        "ix_reading_memory_extraction_jobs_reading_id",
        table_name="reading_memory_extraction_jobs",
    )
    op.drop_table("reading_memory_extraction_jobs")
