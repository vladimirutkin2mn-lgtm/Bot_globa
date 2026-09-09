"""PostgreSQL invariants for one-tap evening daily-horoscope feedback."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.daily_horoscope_models import DailyHoroscopeFeedback
from app.db.models import User
from app.domain.daily_horoscope import (
    DailyHoroscopeClaim,
    DailyHoroscopeFeedbackAnswer,
    DailyHoroscopeMode,
)
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


async def _complete_morning_delivery(
    service: DailyHoroscopePreferenceService,
) -> DailyHoroscopeClaim:
    delivery = await service.claim_due(now=datetime(2026, 8, 27, 5, 0, tzinfo=UTC))
    assert delivery is not None
    assert await service.reserve_send(delivery, now=datetime(2026, 8, 27, 5, 0, tzinfo=UTC))
    assert await service.complete(delivery, now=datetime(2026, 8, 27, 5, 1, tzinfo=UTC))
    return delivery


async def test_evening_feedback_is_default_off_and_not_scheduled(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 976000)
    service = DailyHoroscopePreferenceService(payment_db)
    preference = await service.configure(
        user.id,
        DailyHoroscopeMode.MORNING,
        now=datetime(2026, 8, 27, 4, 59, tzinfo=UTC),
    )
    assert not preference.feedback_enabled

    delivery = await _complete_morning_delivery(service)

    async with payment_db() as session:
        feedback = await session.get(
            DailyHoroscopeFeedback,
            (user.id, delivery.delivery_date),
        )
        assert feedback is None

    assert await service.claim_feedback_due(now=datetime(2026, 8, 27, 17, 30, tzinfo=UTC)) is None


async def test_morning_delivery_schedules_one_local_2030_feedback_prompt_after_opt_in(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 976001)
    service = DailyHoroscopePreferenceService(payment_db)
    await service.configure(
        user.id,
        DailyHoroscopeMode.MORNING,
        now=datetime(2026, 8, 27, 4, 59, tzinfo=UTC),
    )
    preference = await service.set_feedback_enabled(
        user.id,
        True,
        now=datetime(2026, 8, 27, 4, 59, tzinfo=UTC),
    )
    assert preference.feedback_enabled

    delivery = await _complete_morning_delivery(service)

    async with payment_db() as session:
        feedback = await session.get(
            DailyHoroscopeFeedback,
            (user.id, delivery.delivery_date),
        )
        assert feedback is not None
        assert feedback.due_at == datetime(2026, 8, 27, 17, 30, tzinfo=UTC)

    assert await service.claim_feedback_due(now=datetime(2026, 8, 27, 17, 29, tzinfo=UTC)) is None
    prompt = await service.claim_feedback_due(
        now=datetime(2026, 8, 27, 17, 30, tzinfo=UTC),
        lease_seconds=120,
    )
    assert prompt is not None
    assert prompt.user_id == user.id
    assert prompt.telegram_user_id == 976001
    assert prompt.forecast_date == delivery.delivery_date
    assert await service.claim_feedback_due(now=datetime(2026, 8, 27, 17, 30, tzinfo=UTC)) is None

    assert await service.reserve_feedback_prompt(
        prompt,
        now=datetime(2026, 8, 27, 17, 30, tzinfo=UTC),
    )
    assert await service.complete_feedback_prompt(
        prompt,
        now=datetime(2026, 8, 27, 17, 31, tzinfo=UTC),
    )
    assert await service.claim_feedback_due(now=datetime(2026, 8, 27, 18, 0, tzinfo=UTC)) is None


async def test_opt_out_after_claim_prevents_send_and_clears_unsent_prompt(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 976004)
    service = DailyHoroscopePreferenceService(payment_db)
    await service.configure(
        user.id,
        DailyHoroscopeMode.MORNING,
        now=datetime(2026, 8, 27, 4, 59, tzinfo=UTC),
    )
    await service.set_feedback_enabled(
        user.id,
        True,
        now=datetime(2026, 8, 27, 4, 59, tzinfo=UTC),
    )
    delivery = await _complete_morning_delivery(service)
    prompt = await service.claim_feedback_due(now=datetime(2026, 8, 27, 17, 30, tzinfo=UTC))
    assert prompt is not None

    preference = await service.set_feedback_enabled(
        user.id,
        False,
        now=datetime(2026, 8, 27, 17, 30, 30, tzinfo=UTC),
    )
    assert not preference.feedback_enabled
    assert not await service.reserve_feedback_prompt(
        prompt,
        now=datetime(2026, 8, 27, 17, 31, tzinfo=UTC),
    )

    async with payment_db() as session:
        feedback = await session.get(
            DailyHoroscopeFeedback,
            (user.id, delivery.delivery_date),
        )
        assert feedback is None

    await service.set_feedback_enabled(
        user.id,
        True,
        now=datetime(2026, 8, 27, 17, 32, tzinfo=UTC),
    )
    assert await service.claim_feedback_due(now=datetime(2026, 8, 27, 17, 33, tzinfo=UTC)) is None


async def test_daily_feedback_accepts_only_the_first_answer_and_survives_later_opt_out(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 976002)
    service = DailyHoroscopePreferenceService(payment_db)
    await service.configure(
        user.id,
        DailyHoroscopeMode.MORNING,
        now=datetime(2026, 8, 27, 4, 59, tzinfo=UTC),
    )
    await service.set_feedback_enabled(
        user.id,
        True,
        now=datetime(2026, 8, 27, 4, 59, tzinfo=UTC),
    )
    await _complete_morning_delivery(service)
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

    await service.set_feedback_enabled(
        user.id,
        False,
        now=datetime(2026, 8, 27, 17, 33, tzinfo=UTC),
    )

    async with payment_db() as session:
        feedback = await session.get(
            DailyHoroscopeFeedback,
            (user.id, prompt.forecast_date),
        )
        assert feedback is not None
        assert feedback.prompted_at is not None
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
    await service.set_feedback_enabled(
        user.id,
        True,
        now=datetime(2026, 8, 27, 4, 59, tzinfo=UTC),
    )
    delivery = await _complete_morning_delivery(service)

    assert not await service.submit_feedback(
        user.id,
        delivery.delivery_date,
        DailyHoroscopeFeedbackAnswer.USEFUL,
        now=datetime(2026, 8, 27, 17, 0, tzinfo=UTC),
    )
