"""Persist one evening usefulness response per delivered daily horoscope.

Revision ID: 20260827_35
Revises: 20260816_34
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_35"
down_revision: str | None = "20260816_34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_horoscope_feedback",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("forecast_date", sa.Date(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prompt_claim_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prompted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answer", sa.String(length=16), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "answer IS NULL OR answer IN ('useful','not_useful')",
            name="ck_daily_horoscope_feedback_answer",
        ),
        sa.CheckConstraint(
            "(answer IS NULL AND answered_at IS NULL) OR "
            "(answer IS NOT NULL AND answered_at IS NOT NULL)",
            name="ck_daily_horoscope_feedback_answered",
        ),
        sa.CheckConstraint(
            "(prompt_claim_id IS NULL AND prompt_lease_until IS NULL) OR "
            "(prompt_claim_id IS NOT NULL AND prompt_lease_until IS NOT NULL)",
            name="ck_daily_horoscope_feedback_claim",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "forecast_date"),
    )
    op.create_index(
        "ix_daily_horoscope_feedback_due_at",
        "daily_horoscope_feedback",
        ["due_at"],
    )
    op.create_index(
        "ix_daily_horoscope_feedback_prompt_claim_id",
        "daily_horoscope_feedback",
        ["prompt_claim_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_daily_horoscope_feedback_prompt_claim_id",
        table_name="daily_horoscope_feedback",
    )
    op.drop_index(
        "ix_daily_horoscope_feedback_due_at",
        table_name="daily_horoscope_feedback",
    )
    op.drop_table("daily_horoscope_feedback")
