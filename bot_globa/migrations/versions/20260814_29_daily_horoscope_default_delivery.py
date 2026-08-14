"""Send the daily horoscope at 08:00 by default.

Revision ID: 20260814_29
Revises: 20260813_28
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_29"
down_revision: str | None = "20260813_28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MOVE_LEGACY_MODES_TO_MORNING = """
UPDATE daily_horoscope_preferences
SET mode = 'morning',
    next_delivery_at = (
        CASE
            WHEN timezone('Europe/Moscow', CURRENT_TIMESTAMP)::time < TIME '08:00'
                THEN timezone('Europe/Moscow', CURRENT_TIMESTAMP)::date
            ELSE timezone('Europe/Moscow', CURRENT_TIMESTAMP)::date + 1
        END + TIME '08:00'
    ) AT TIME ZONE 'Europe/Moscow',
    claim_id = NULL,
    lease_until = NULL,
    updated_at = CURRENT_TIMESTAMP
WHERE mode IN ('evening', 'on_request')
"""

_BACKFILL_DEFAULT_MORNINGS = """
INSERT INTO daily_horoscope_preferences (
    user_id,
    mode,
    timezone,
    next_delivery_at,
    created_at,
    updated_at
)
SELECT
    users.id,
    'morning',
    'Europe/Moscow',
    (
        CASE
            WHEN timezone('Europe/Moscow', CURRENT_TIMESTAMP)::time < TIME '08:00'
                THEN timezone('Europe/Moscow', CURRENT_TIMESTAMP)::date
            ELSE timezone('Europe/Moscow', CURRENT_TIMESTAMP)::date + 1
        END + TIME '08:00'
    ) AT TIME ZONE 'Europe/Moscow',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
FROM users
LEFT JOIN daily_horoscope_preferences AS preferences
    ON preferences.user_id = users.id
WHERE preferences.user_id IS NULL
  AND users.telegram_user_id IS NOT NULL
  AND users.privacy_status <> 'deleted'
ON CONFLICT (user_id) DO NOTHING
"""


def upgrade() -> None:
    connection = op.get_bind()
    op.alter_column(
        "daily_horoscope_preferences",
        "mode",
        existing_type=sa.String(length=16),
        server_default="morning",
        existing_nullable=False,
    )

    # `on_request` was the old default, not an explicit opt-out. Move it and the old
    # evening opt-in to the new single 08:00 slot; leave only explicit `disabled` rows off.
    connection.execute(sa.text(_MOVE_LEGACY_MODES_TO_MORNING))
    # Everyone who has not made a delivery choice starts with tomorrow's/today's 08:00
    # Moscow schedule. New accounts receive the same row from OnboardingService.
    connection.execute(sa.text(_BACKFILL_DEFAULT_MORNINGS))


def downgrade() -> None:
    # Keep real user choices and provisioned rows: deleting or guessing them would be a
    # data-losing downgrade. Only restore the old schema default.
    op.alter_column(
        "daily_horoscope_preferences",
        "mode",
        existing_type=sa.String(length=16),
        server_default="on_request",
        existing_nullable=False,
    )
