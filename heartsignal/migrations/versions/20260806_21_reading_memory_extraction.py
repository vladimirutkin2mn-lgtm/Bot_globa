"""Add completed-reading memory extraction metadata.

Revision ID: 20260806_21
Revises: 20260806_20
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_21"
down_revision: str | None = "20260806_20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "oracle_memory_items",
        sa.Column(
            "claim_basis",
            sa.String(length=24),
            server_default="user_stated",
            nullable=False,
        ),
    )
    op.add_column(
        "oracle_memory_items",
        sa.Column("candidate_key", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE oracle_memory_items "
            "SET candidate_key = 'legacy-' || replace(id::text, '-', '') "
            "WHERE source_type = 'reading_derived' AND candidate_key IS NULL"
        )
    )

    op.drop_constraint(
        "ck_oracle_memory_items_kind",
        "oracle_memory_items",
        type_="check",
    )
    op.create_check_constraint(
        "ck_oracle_memory_items_kind",
        "oracle_memory_items",
        "kind IN ('user_statement','user_preference','personal_goal',"
        "'relationship_notes','recurring_theme','birth_profile','oracle_preference')",
    )
    op.create_check_constraint(
        "ck_oracle_memory_items_claim_basis",
        "oracle_memory_items",
        "claim_basis IN ('user_stated','model_inferred')",
    )
    op.create_check_constraint(
        "ck_oracle_memory_items_provenance",
        "oracle_memory_items",
        "(source_type = 'reading_derived' AND candidate_key IS NOT NULL) OR "
        "(source_type <> 'reading_derived' AND source_reading_id IS NULL "
        "AND candidate_key IS NULL)",
    )
    op.create_index(
        "ix_oracle_memory_items_extraction_lookup",
        "oracle_memory_items",
        [
            "user_id",
            "source_reading_id",
            "extraction_version",
            "candidate_key",
            "status",
        ],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    incompatible_rows = connection.execute(
        sa.text(
            "SELECT count(*) FROM oracle_memory_items "
            "WHERE kind = 'user_statement' OR claim_basis <> 'user_stated'"
        )
    ).scalar_one()
    if incompatible_rows:
        raise RuntimeError("downgrade refused: oracle memory extraction metadata would be lost")

    op.drop_index(
        "ix_oracle_memory_items_extraction_lookup",
        table_name="oracle_memory_items",
    )
    op.drop_constraint(
        "ck_oracle_memory_items_provenance",
        "oracle_memory_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_oracle_memory_items_claim_basis",
        "oracle_memory_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_oracle_memory_items_kind",
        "oracle_memory_items",
        type_="check",
    )
    op.create_check_constraint(
        "ck_oracle_memory_items_kind",
        "oracle_memory_items",
        "kind IN ('user_preference','personal_goal','relationship_notes',"
        "'recurring_theme','birth_profile','oracle_preference')",
    )
    op.drop_column("oracle_memory_items", "candidate_key")
    op.drop_column("oracle_memory_items", "claim_basis")
