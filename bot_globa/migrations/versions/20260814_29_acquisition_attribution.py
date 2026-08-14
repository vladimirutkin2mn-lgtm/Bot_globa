"""add immutable acquisition attribution

Revision ID: 20260814_29
Revises: 20260813_28
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260814_29"
down_revision: str | None = "20260813_28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "acquisition_attributions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=16), server_default="partizan", nullable=False),
        sa.Column("experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("source = 'partizan'", name="ck_acquisition_attributions_source"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        "ix_acquisition_attributions_experiment_id",
        "acquisition_attributions",
        ["experiment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_acquisition_attributions_experiment_id",
        table_name="acquisition_attributions",
    )
    op.drop_table("acquisition_attributions")
