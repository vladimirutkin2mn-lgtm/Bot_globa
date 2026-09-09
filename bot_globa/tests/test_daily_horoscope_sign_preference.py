"""Compact daily sign preference stays separate from natal personalization."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.daily_horoscope import render_compact_daily_horoscope, render_daily_horoscope
from app.db.daily_horoscope_models import DailyHoroscopePreference
from app.db.models import User
from app.domain.natal_chart import ZodiacSign
from app.services.daily_horoscope import DailyHoroscopePreferenceService
from app.services.daily_horoscope_editorial import build_editorial_daily_horoscope
from app.services.daily_sky import SIGN_LABELS
from app.services.onboarding import CURRENT_CONSENT_VERSION


def test_compact_daily_uses_the_same_shared_snapshot_but_only_one_sign() -> None:
    snapshot = build_editorial_daily_horoscope(date(2026, 9, 9))
    compact = render_compact_daily_horoscope(snapshot, ZodiacSign.ARIES)
    full = render_daily_horoscope(snapshot)
    aries = next(item for item in snapshot.signs if item.sign is ZodiacSign.ARIES)
    taurus = next(item for item in snapshot.signs if item.sign is ZodiacSign.TAURUS)

    assert snapshot.theme in compact
    assert aries.text in compact
    assert SIGN_LABELS[ZodiacSign.ARIES][1] in compact
    assert taurus.text not in compact
    assert SIGN_LABELS[ZodiacSign.TAURUS][1] not in compact
    assert len(compact) < len(full)
    assert "общий прогноз по знаку" in compact
    assert "натальную карту" in compact


@pytest.mark.postgres
async def test_solar_sign_is_persisted_only_as_a_daily_preference(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    async with payment_db.begin() as session:
        user = User(
            telegram_user_id=976001,
            first_name="Daily sign",
            consent_version=CURRENT_CONSENT_VERSION,
        )
        session.add(user)
        await session.flush()
        user_id = user.id

    service = DailyHoroscopePreferenceService(payment_db)
    saved = await service.set_zodiac_sign(
        user_id,
        ZodiacSign.ARIES,
        now=datetime(2026, 9, 9, 5, 0, tzinfo=UTC),
    )

    assert saved.zodiac_sign is ZodiacSign.ARIES
    assert (await service.current(user_id)).zodiac_sign is ZodiacSign.ARIES
    async with payment_db() as session:
        row = await session.get(DailyHoroscopePreference, user_id)
        assert row is not None
        assert row.zodiac_sign == ZodiacSign.ARIES.value

    cleared = await service.set_zodiac_sign(
        user_id,
        None,
        now=datetime(2026, 9, 9, 5, 1, tzinfo=UTC),
    )
    assert cleared.zodiac_sign is None
