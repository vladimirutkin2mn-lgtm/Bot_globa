"""durable paid follow-up entitlement for readings

Revision ID: 20260809_25
Revises: 20260806_24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260809_25"
down_revision: str | None = "20260806_24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reading_followups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reading_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="available", nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("question_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("answer_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("reservation_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("llm_attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("llm_provider", sa.String(length=32), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("last_failure_code", sa.String(length=64), nullable=True),
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
            "status IN ('available','reserved','completed')",
            name="ck_reading_followups_status",
        ),
        sa.CheckConstraint(
            "reservation_count >= 0 AND llm_attempt_count >= 0",
            name="ck_reading_followups_attempts",
        ),
        sa.CheckConstraint(
            "(status = 'available' AND claim_id IS NULL AND lease_until IS NULL "
            "AND question_ciphertext IS NULL AND answer_ciphertext IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'reserved' AND claim_id IS NOT NULL AND lease_until IS NOT NULL "
            "AND question_ciphertext IS NOT NULL AND answer_ciphertext IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'completed' AND claim_id IS NULL AND lease_until IS NULL "
            "AND question_ciphertext IS NOT NULL AND answer_ciphertext IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="ck_reading_followups_state",
        ),
        sa.ForeignKeyConstraint(["reading_id"], ["readings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reading_id", name="uq_reading_followups_reading"),
    )
    op.create_index(
        "ix_reading_followups_user_id",
        "reading_followups",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_reading_followups_expired_reservations",
        "reading_followups",
        ["lease_until"],
        unique=False,
        postgresql_where=sa.text("status = 'reserved'"),
    )
    # Soft-deleting a reading must take its follow-up ciphertext with it.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION purge_reading_followup_on_delete()
        RETURNS trigger AS $$
        BEGIN
          IF NEW.status = 'deleted' AND OLD.status IS DISTINCT FROM 'deleted' THEN
            DELETE FROM reading_followups WHERE reading_id = NEW.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_purge_reading_followup_on_delete ON readings")
    op.execute(
        """
        CREATE TRIGGER trg_purge_reading_followup_on_delete
        AFTER UPDATE OF status ON readings
        FOR EACH ROW EXECUTE FUNCTION purge_reading_followup_on_delete()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_purge_reading_followup_on_delete ON readings")
    op.execute("DROP FUNCTION IF EXISTS purge_reading_followup_on_delete()")
    op.drop_index("ix_reading_followups_expired_reservations", table_name="reading_followups")
    op.drop_index("ix_reading_followups_user_id", table_name="reading_followups")
    op.drop_table("reading_followups")
