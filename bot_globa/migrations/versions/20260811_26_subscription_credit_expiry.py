"""expire unused subscription credits at period end

Revision ID: 20260811_26
Revises: 20260809_25
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_26"
down_revision: str | None = "20260809_25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES_WITHOUT_EXPIRY = "'grant','purchase','spend','refund','adjustment','purchase_refund'"
_TYPES_WITH_EXPIRY = f"{_TYPES_WITHOUT_EXPIRY},'expiry'"

_SIGN_WITHOUT_EXPIRY = (
    "(type IN ('grant','purchase','refund') AND amount > 0) OR "
    "(type = 'purchase_refund' AND amount < 0) OR "
    "(type = 'spend' AND amount < 0) OR "
    "(type = 'adjustment' AND amount <> 0)"
)
_SIGN_WITH_EXPIRY = (
    "(type IN ('grant','purchase','refund') AND amount > 0) OR "
    "(type = 'purchase_refund' AND amount < 0) OR "
    "(type IN ('spend','expiry') AND amount < 0) OR "
    "(type = 'adjustment' AND amount <> 0)"
)


def upgrade() -> None:
    op.add_column(
        "subscription_periods",
        sa.Column("credits_expired_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Finished periods that predate this revision were sold as permanent credits and are
    # marked settled, so the new sweep can never retroactively take them away.
    op.execute("UPDATE subscription_periods SET credits_expired_at = now()")
    op.drop_constraint("ck_credit_transactions_type", "credit_transactions", type_="check")
    op.create_check_constraint(
        "ck_credit_transactions_type",
        "credit_transactions",
        f"type IN ({_TYPES_WITH_EXPIRY})",
    )
    op.drop_constraint("ck_credit_transactions_sign", "credit_transactions", type_="check")
    op.create_check_constraint(
        "ck_credit_transactions_sign",
        "credit_transactions",
        _SIGN_WITH_EXPIRY,
    )
    op.create_index(
        "ix_subscription_periods_pending_expiry",
        "subscription_periods",
        ["period_end"],
        postgresql_where=sa.text("credits_expired_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_periods_pending_expiry", table_name="subscription_periods")
    # The ledger is append-only, so an expiry that already happened is reclassified rather
    # than deleted: 'adjustment' also carries a negative amount, and every balance derived
    # before and after this downgrade is identical.
    op.execute("UPDATE credit_transactions SET type = 'adjustment' WHERE type = 'expiry'")
    op.drop_constraint("ck_credit_transactions_sign", "credit_transactions", type_="check")
    op.create_check_constraint(
        "ck_credit_transactions_sign",
        "credit_transactions",
        _SIGN_WITHOUT_EXPIRY,
    )
    op.drop_constraint("ck_credit_transactions_type", "credit_transactions", type_="check")
    op.create_check_constraint(
        "ck_credit_transactions_type",
        "credit_transactions",
        f"type IN ({_TYPES_WITHOUT_EXPIRY})",
    )
    op.drop_column("subscription_periods", "credits_expired_at")
