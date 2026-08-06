"""Add durable oracle memory lifecycle metadata and event ledger.

Revision ID: 20260806_23
Revises: 20260806_22
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_23"
down_revision: str | None = "20260806_22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPES = (
    "created",
    "extracted",
    "used",
    "deleted",
    "corrected",
    "deduplicated",
    "superseded",
    "decayed",
    "capacity_retired",
)


def upgrade() -> None:
    op.add_column(
        "oracle_memory_items",
        sa.Column("use_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "oracle_memory_items",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "oracle_memory_items",
        sa.Column("supersedes_item_id", sa.Uuid(), nullable=True),
    )
    op.create_check_constraint(
        "ck_oracle_memory_items_use_count",
        "oracle_memory_items",
        "use_count >= 0",
    )
    op.create_foreign_key(
        "fk_oracle_memory_items_supersedes_item_id",
        "oracle_memory_items",
        "oracle_memory_items",
        ["supersedes_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_oracle_memory_items_supersedes_item_id",
        "oracle_memory_items",
        ["supersedes_item_id"],
        unique=False,
    )

    op.create_table(
        "oracle_memory_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("memory_item_id", sa.Uuid(), nullable=True),
        sa.Column("related_memory_item_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN (" + ",".join(f"'{value}'" for value in _EVENT_TYPES) + ")",
            name="ck_oracle_memory_events_type",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["memory_item_id"],
            ["oracle_memory_items.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["related_memory_item_id"],
            ["oracle_memory_items.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_oracle_memory_events_user_type_created",
        "oracle_memory_events",
        ["user_id", "event_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_oracle_memory_events_memory_item_id",
        "oracle_memory_events",
        ["memory_item_id"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    event_rows = connection.execute(
        sa.text("SELECT count(*) FROM oracle_memory_events")
    ).scalar_one()
    lifecycle_rows = connection.execute(
        sa.text(
            "SELECT count(*) FROM oracle_memory_items "
            "WHERE use_count <> 0 OR last_used_at IS NOT NULL OR supersedes_item_id IS NOT NULL"
        )
    ).scalar_one()
    if event_rows or lifecycle_rows:
        raise RuntimeError("downgrade refused: oracle memory lifecycle history would be lost")

    op.drop_index("ix_oracle_memory_events_memory_item_id", table_name="oracle_memory_events")
    op.drop_index("ix_oracle_memory_events_user_type_created", table_name="oracle_memory_events")
    op.drop_table("oracle_memory_events")
    op.drop_index(
        "ix_oracle_memory_items_supersedes_item_id",
        table_name="oracle_memory_items",
    )
    op.drop_constraint(
        "fk_oracle_memory_items_supersedes_item_id",
        "oracle_memory_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_oracle_memory_items_use_count",
        "oracle_memory_items",
        type_="check",
    )
    op.drop_column("oracle_memory_items", "supersedes_item_id")
    op.drop_column("oracle_memory_items", "last_used_at")
    op.drop_column("oracle_memory_items", "use_count")
