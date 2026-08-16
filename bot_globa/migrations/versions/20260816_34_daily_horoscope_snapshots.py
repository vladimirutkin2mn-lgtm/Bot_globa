"""persist one immutable mass daily horoscope snapshot per date

Revision ID: 20260816_34
Revises: 20260816_33
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_34"
down_revision: str | None = "20260816_33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_horoscope_snapshots",
        sa.Column("forecast_date", sa.Date(), nullable=False),
        sa.Column("sky_version", sa.String(length=64), nullable=False),
        sa.Column("methodology_version", sa.String(length=64), nullable=False),
        sa.Column("sky_digest", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("forecast_date"),
    )


def downgrade() -> None:
    op.drop_table("daily_horoscope_snapshots")
