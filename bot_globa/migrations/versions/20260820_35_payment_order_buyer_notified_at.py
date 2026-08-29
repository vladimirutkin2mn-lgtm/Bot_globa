"""record when the buyer was told their payment landed

Revision ID: 20260820_35
Revises: 20260816_34
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_35"
down_revision: str | None = "20260816_34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payment_orders",
        sa.Column("buyer_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # A hosted checkout completes in a worker, long after the buyer left the bot, so the
    # notification is claimed from this partial index rather than by scanning every order.
    op.create_index(
        "ix_payment_orders_pending_buyer_notification",
        "payment_orders",
        ["completed_at"],
        unique=False,
        postgresql_where=sa.text("status = 'completed' AND buyer_notified_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_orders_pending_buyer_notification",
        table_name="payment_orders",
        postgresql_where=sa.text("status = 'completed' AND buyer_notified_at IS NULL"),
    )
    op.drop_column("payment_orders", "buyer_notified_at")
