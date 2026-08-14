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

_MOVE_EVENING_OPT_INS_TO_MORNING = """
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
WHERE mode = 'evening'
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
    # Drop the column default rather than move it to 'morning'. The schedule check
    # constraint ties the mode to whether `next_delivery_at` is set, and that column
    # cannot carry a default, so a 'morning' default would make every insert that relies
    # on it fail. Every writer states both columns instead.
    op.alter_column(
        "daily_horoscope_preferences",
        "mode",
        existing_type=sa.String(length=16),
        server_default=None,
        existing_nullable=False,
    )

    # Only `evening` moves: it was an explicit opt-in to a scheduled digest, and the new
    # product has a single 08:00 slot. `on_request` is left alone on purpose — this table
    # has never been backfilled (revision 20260813_27 creates it empty) and the only writer
    # was an explicit tap on `daily:set:*`, so every `on_request` row is a user who chose
    # "Только по запросу" and was told automatic delivery was off. Re-enabling those would
    # push an unsolicited daily message to someone who declined it.
    connection.execute(sa.text(_MOVE_EVENING_OPT_INS_TO_MORNING))
    # Everyone who never opened the settings screen at all starts with the default 08:00
    # Moscow schedule. New accounts receive the same row from OnboardingService, and
    # delivery waits for consent in `claim_due` either way.
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
