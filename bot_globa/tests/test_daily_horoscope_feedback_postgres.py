"""PostgreSQL invariants for one-tap evening daily-horoscope feedback."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.daily_horoscope_models import DailyHoroscopeFeedback
from app.db.models import User
from app.domain.daily_horoscope import DailyHoroscopeFeedbackAnswer, DailyHoroscopeMode
from app.services.daily_horoscope import DailyHoroscopePreferenceService
from app.services.onboarding import CURRENT_CONSENT_VERSION

pytestmark = pytest.mark.postgres


async def _user(
    sessions: async_sessionmaker[AsyncSession],
    telegram_id: int,
) -> User:
    async with sessions.begin() as session:
        user = User(
            telegram_user_id=telegram_id,
            first_name="Feedback",
            consent_version=CURRENT_CONSENT_VERSION,
        )
        session.add(user)
        await session.flush()
        return user


async def test_morning_delivery_schedules_one_local_2030_feedback_prompt(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 976001)
    service = DailyHoroscopePreferenceService(payment_db)
    await service.configure(
        user.id,
        DailyHoroscopeMode.MORNING,
        now=datetime(2026, 8, 27, 4, 59, tzinfo=UTC),
    )

    delivery = await service.claim_due(now=datetime(2026, 8, 27, 5, 0, tzinfo=UTC))
    assert delivery is not None
    assert await service.reserve_send(delivery, now=datetime(2026, 8, 27, 5, 0, tzinfo=UTC))
    assert await service.complete(delivery, now=datetime(2026, 8, 27, 5, 1, tzinfo=UTC))

    async with payment_db() as session:
        feedback = await session.get(
            DailyHoroscopeFeedback,
            (user.id, delivery.delivery_date),
        )
        assert feedback is not None
        assert feedback.due_at == datetime(2026, 8, 27, 17, 30, tzinfo=UTC)

    assert (
        await service.claim_feedback_due(now=datetime(2026, 8, 27, 17, 29, tzinfo=UTC))
        is None
    )
    prompt = await service.claim_feedback_due(
        now=datetime(2026, 8, 27, 17, 30, tzinfo=UTC),
        lease_seconds=120,
    )
    assert prompt is not None
    assert prompt.user_id == user.id
    assert prompt.telegram_user_id == 976001
    assert prompt.forecast_date == delivery.delivery_date
    assert (
        await service.claim_feedback_due(now=datetime(2026, 8, 27, 17, 30, tzinfo=UTC))
        is None
    )

    assert await service.reserve_feedback_prompt(
        prompt,
        now=datetime(2026, 8, 27, 17, 30, tzinfo=UTC),
    )
    assert await service.complete_feedback_prompt(
        prompt,
        now=datetime(2026, 8, 27, 17, 31, tzinfo=UTC),
    )
    assert (
        await service.claim_feedback_due(now=datetime(2026, 8, 27, 18, 0, tzinfo=UTC))
        is None
    )


async def test_daily_feedback_accepts_only_the_first_answer(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 976002)
    service = DailyHoroscopePreferenceService(payment_db)
    await service.configure(
        user.id,
        DailyHoroscopeMode.MORNING,
        now=datetime(2026, 8, 27, 4, 59, tzinfo=UTC),
    )
    delivery = await service.claim_due(now=datetime(2026, 8, 27, 5, 0, tzinfo=UTC))
    assert delivery is not None
    assert await service.reserve_send(delivery, now=datetime(2026, 8, 27, 5, 0, tzinfo=UTC))
    assert await service.complete(delivery, now=datetime(2026, 8, 27, 5, 1, tzinfo=UTC))
    prompt = await service.claim_feedback_due(now=datetime(2026, 8, 27, 17, 30, tzinfo=UTC))
    assert prompt is not None
    assert await service.reserve_feedback_prompt(
        prompt,
        now=datetime(2026, 8, 27, 17, 30, tzinfo=UTC),
    )
    assert await service.complete_feedback_prompt(prompt)

    assert await service.submit_feedback(
        user.id,
        prompt.forecast_date,
        DailyHoroscopeFeedbackAnswer.USEFUL,
        now=datetime(2026, 8, 27, 17, 31, tzinfo=UTC),
    )
    assert not await service.submit_feedback(
        user.id,
        prompt.forecast_date,
        DailyHoroscopeFeedbackAnswer.NOT_USEFUL,
        now=datetime(2026, 8, 27, 17, 32, tzinfo=UTC),
    )

    async with payment_db() as session:
        feedback = await session.get(
            DailyHoroscopeFeedback,
            (user.id, prompt.forecast_date),
        )
        assert feedback is not None
        assert feedback.answer == DailyHoroscopeFeedbackAnswer.USEFUL.value
        assert feedback.answered_at == datetime(2026, 8, 27, 17, 31, tzinfo=UTC)


async def test_feedback_is_not_accepted_before_the_prompt_is_reserved(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 976003)
    service = DailyHoroscopePreferenceService(payment_db)
    await service.configure(
        user.id,
        DailyHoroscopeMode.MORNING,
        now=datetime(2026, 8, 27, 4, 59, tzinfo=UTC),
    )
    delivery = await service.claim_due(now=datetime(2026, 8, 27, 5, 0, tzinfo=UTC))
    assert delivery is not None
    assert await service.reserve_send(delivery, now=datetime(2026, 8, 27, 5, 0, tzinfo=UTC))
    assert await service.complete(delivery, now=datetime(2026, 8, 27, 5, 1, tzinfo=UTC))

    assert not await service.submit_feedback(
        user.id,
        delivery.delivery_date,
        DailyHoroscopeFeedbackAnswer.USEFUL,
        now=datetime(2026, 8, 27, 17, 0, tzinfo=UTC),
    )
