"""Store an optional zodiac sign for the compact common daily horoscope.

Revision ID: 20260909_38
Revises: 20260908_37
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_38"
down_revision: str | None = "20260908_37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ZODIAC_CHECK = (
    "zodiac_sign IS NULL OR zodiac_sign IN ("
    "'aries','taurus','gemini','cancer','leo','virgo','libra','scorpio',"
    "'sagittarius','capricorn','aquarius','pisces')"
)


def upgrade() -> None:
    op.add_column(
        "daily_horoscope_preferences",
        sa.Column("zodiac_sign", sa.String(length=16), nullable=True),
    )
    op.create_check_constraint(
        "ck_daily_horoscope_preferences_zodiac_sign",
        "daily_horoscope_preferences",
        _ZODIAC_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_daily_horoscope_preferences_zodiac_sign",
        "daily_horoscope_preferences",
        type_="check",
    )
    op.drop_column("daily_horoscope_preferences", "zodiac_sign")
