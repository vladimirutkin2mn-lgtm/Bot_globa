"""Add voluntary daily-horoscope delivery preferences.

Revision ID: 20260813_27
Revises: 20260811_26
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_27"
down_revision: str | None = "20260811_26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_horoscope_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=16), server_default="on_request", nullable=False),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default="Europe/Moscow",
            nullable=False,
        ),
        sa.Column("next_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_id", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivered_on", sa.Date(), nullable=True),
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
            "mode IN ('morning','evening','on_request','disabled')",
            name="ck_daily_horoscope_preferences_mode",
        ),
        sa.CheckConstraint(
            "(mode IN ('morning','evening') AND next_delivery_at IS NOT NULL) OR "
            "(mode IN ('on_request','disabled') AND next_delivery_at IS NULL)",
            name="ck_daily_horoscope_preferences_schedule",
        ),
        sa.CheckConstraint(
            "(claim_id IS NULL AND lease_until IS NULL) OR "
            "(claim_id IS NOT NULL AND lease_until IS NOT NULL)",
            name="ck_daily_horoscope_preferences_claim",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        "ix_daily_horoscope_preferences_next_delivery_at",
        "daily_horoscope_preferences",
        ["next_delivery_at"],
    )
    op.create_index(
        "ix_daily_horoscope_preferences_claim_id",
        "daily_horoscope_preferences",
        ["claim_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    row_count = connection.execute(
        sa.text("SELECT count(*) FROM daily_horoscope_preferences")
    ).scalar_one()
    if row_count:
        raise RuntimeError("downgrade refused: daily horoscope preferences would be lost")
    op.drop_index(
        "ix_daily_horoscope_preferences_claim_id",
        table_name="daily_horoscope_preferences",
    )
    op.drop_index(
        "ix_daily_horoscope_preferences_next_delivery_at",
        table_name="daily_horoscope_preferences",
    )
    op.drop_table("daily_horoscope_preferences")
