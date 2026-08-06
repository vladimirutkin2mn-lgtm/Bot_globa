"""PostgreSQL boundary between encrypted BirthProfile storage and pure calculation."""

from datetime import date, time

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.domain.birth_profile import BirthProfileInput
from app.domain.natal_chart import NatalTimePrecision
from app.services.birth_profile import (
    BirthProfileConsentRequiredError,
    BirthProfileService,
)
from app.services.natal_chart import (
    AstronomyEngineNatalChartCalculator,
    BirthProfileUnavailableError,
    ConsentedNatalChartService,
)
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres


async def test_chart_calculation_requires_active_consented_profile(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    async with payment_db.begin() as session:
        user = User(telegram_user_id=896101, first_name="Natal Consent")
        session.add(user)
        await session.flush()

    profiles = BirthProfileService(
        payment_db,
        AESGCMSensitiveContentCipher("natal-consent-boundary-key"),
    )
    charts = ConsentedNatalChartService(
        profiles,
        AstronomyEngineNatalChartCalculator(),
    )

    with pytest.raises(BirthProfileConsentRequiredError):
        await charts.calculate_for_user(user.id)

    await profiles.grant_consent(user.id)
    with pytest.raises(BirthProfileUnavailableError):
        await charts.calculate_for_user(user.id)

    await profiles.save(
        user.id,
        BirthProfileInput(
            birth_date=date(1991, 4, 17),
            birth_time=time(8, 35),
            birth_place="Amsterdam",
            timezone="Europe/Amsterdam",
            latitude=52.367573,
            longitude=4.904139,
            utc_offset_minutes=120,
        ),
    )
    result = await charts.calculate_for_user(user.id)

    assert result.time_precision is NatalTimePrecision.EXACT
    assert len(result.planets) == 10
    assert len(result.houses) == 12

    await profiles.revoke_consent(user.id)
    with pytest.raises(BirthProfileConsentRequiredError):
        await charts.calculate_for_user(user.id)
