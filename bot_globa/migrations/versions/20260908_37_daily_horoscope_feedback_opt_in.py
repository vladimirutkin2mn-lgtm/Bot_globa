"""Require explicit opt-in before sending evening daily-horoscope feedback.

Revision ID: 20260908_37
Revises: 20260829_36
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_37"
down_revision: str | None = "20260829_36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_horoscope_preferences",
        sa.Column(
            "feedback_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    # Legacy rows were queued before evening feedback had a separate opt-in.
    # Preserve already-sent/answered history, but never resurrect unsent prompts.
    op.execute(sa.text("DELETE FROM daily_horoscope_feedback WHERE prompted_at IS NULL"))


def downgrade() -> None:
    op.drop_column("daily_horoscope_preferences", "feedback_enabled")
