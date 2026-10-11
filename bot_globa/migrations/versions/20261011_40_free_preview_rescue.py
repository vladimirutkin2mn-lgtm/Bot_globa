"""Add a durable one-time free preview rescue marker.

Revision ID: 20261011_40
Revises: 20260911_39
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261011_40"
down_revision: str | None = "20260911_39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("free_preview_rescue_used_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "free_preview_rescue_used_at")
