"""single in-flight pre-checkout authorization per payment order

Revision ID: 20260813_28
Revises: 20260813_27
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_28"
down_revision: str | None = "20260813_27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Telegram Stars invoices are provider-hosted: one order can back several invoice messages,
    # so the pre-checkout answer is the only place a second concurrent charge can be refused.
    op.add_column(
        "payment_orders",
        sa.Column("pre_checkout_query_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "payment_orders",
        sa.Column("pre_checkout_authorized_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payment_orders", "pre_checkout_authorized_at")
    op.drop_column("payment_orders", "pre_checkout_query_id")
