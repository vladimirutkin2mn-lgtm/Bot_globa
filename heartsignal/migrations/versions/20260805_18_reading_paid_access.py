"""add paid access linkage for oracle readings

Revision ID: 20260805_18
Revises: 20260805_17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260805_18"
down_revision: str | None = "20260805_17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "credit_transactions",
        sa.Column("reading_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_credit_transactions_reading",
        "credit_transactions",
        "readings",
        ["reading_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_credit_transactions_reading_id",
        "credit_transactions",
        ["reading_id"],
        unique=False,
    )
    op.drop_constraint(
        "ck_credit_transactions_spend_analysis",
        "credit_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_credit_transactions_spend_target",
        "credit_transactions",
        "type <> 'spend' OR ((analysis_id IS NOT NULL AND reading_id IS NULL) OR "
        "(analysis_id IS NULL AND reading_id IS NOT NULL))",
    )

    op.add_column(
        "readings",
        sa.Column("full_access_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_readings_full_transaction",
        "readings",
        "credit_transactions",
        ["full_access_transaction_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )

    # A pre-monetization full flag has no ledger evidence. Preserve the encrypted
    # result, but fail closed to preview until the user purchases full access.
    op.execute(
        sa.text(
            "UPDATE readings SET status='preview_ready', access_level='preview', cost_units=0 "
            "WHERE status='full_ready'"
        )
    )
    op.execute(sa.text("UPDATE readings SET cost_units=0 WHERE status <> 'full_ready'"))
    op.create_check_constraint(
        "ck_readings_paid_access",
        "readings",
        "(status = 'full_ready' AND access_level = 'full' AND cost_units > 0 "
        "AND full_access_transaction_id IS NOT NULL) OR "
        "(status = 'deleted' AND access_level = 'none' AND "
        "((cost_units = 0 AND full_access_transaction_id IS NULL) OR "
        "(cost_units > 0 AND full_access_transaction_id IS NOT NULL))) OR "
        "(status NOT IN ('full_ready','deleted') AND cost_units = 0 "
        "AND full_access_transaction_id IS NULL)",
    )


def downgrade() -> None:
    bind = op.get_bind()
    linked_spends = bind.scalar(
        sa.text("SELECT count(*) FROM credit_transactions WHERE reading_id IS NOT NULL")
    )
    paid_readings = bind.scalar(
        sa.text("SELECT count(*) FROM readings WHERE full_access_transaction_id IS NOT NULL")
    )
    if linked_spends or paid_readings:
        raise RuntimeError("downgrade refused: paid reading ledger state exists")

    op.drop_constraint("ck_readings_paid_access", "readings", type_="check")
    op.drop_constraint("fk_readings_full_transaction", "readings", type_="foreignkey")
    op.drop_column("readings", "full_access_transaction_id")

    op.drop_constraint(
        "ck_credit_transactions_spend_target",
        "credit_transactions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_credit_transactions_spend_analysis",
        "credit_transactions",
        "type <> 'spend' OR analysis_id IS NOT NULL",
    )
    op.drop_index("ix_credit_transactions_reading_id", table_name="credit_transactions")
    op.drop_constraint(
        "fk_credit_transactions_reading",
        "credit_transactions",
        type_="foreignkey",
    )
    op.drop_column("credit_transactions", "reading_id")
