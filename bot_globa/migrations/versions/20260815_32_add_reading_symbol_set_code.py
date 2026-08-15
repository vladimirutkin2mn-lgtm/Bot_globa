"""freeze the selected symbol set on every reading

Revision ID: 20260815_32
Revises: 20260814_31
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_32"
down_revision: str | None = "20260814_31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist the symbol/spread contract chosen when a Reading is drafted."""

    op.add_column(
        "readings",
        sa.Column(
            "symbol_set_code",
            sa.String(length=64),
            server_default="none",
            nullable=False,
        ),
    )
    # All Tarot readings created before this revision used the one legacy three-card
    # layout. Freezing that fact preserves retry/replay after topic-specific layouts ship.
    op.execute(
        """
        UPDATE readings
        SET symbol_set_code = 'three_card_v1'
        WHERE engine_version IN ('tarot-symbolic-v1', 'tarot-symbolic-v2')
        """
    )


def downgrade() -> None:
    """Remove the frozen symbol-set metadata."""

    op.drop_column("readings", "symbol_set_code")
