"""Regression coverage for restoring the daily-personal horoscope entry intent."""

from typing import cast
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from app.bot import horoscope_intent
from app.bot.states import HoroscopeStates


def _state() -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=42, user_id=42),
    )


async def test_daily_intent_survives_state_transitions_and_is_consumed_on_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    screen = AsyncMock()
    monkeypatch.setattr(horoscope_intent, "show_screen", screen)

    await horoscope_intent.remember_horoscope_intent(
        state,
        horoscope_intent.DAY_FORECAST_INTENT,
    )
    await state.set_state(HoroscopeStates.waiting_for_birth_date)

    assert (await state.get_data())[horoscope_intent.PENDING_HOROSCOPE_INTENT_KEY] == "day_forecast"

    resumed = await horoscope_intent.resume_horoscope_intent(cast("Message", object()), state)

    assert resumed is True
    assert await state.get_state() == HoroscopeStates.waiting_for_question.state
    assert await state.get_data() == {"topic": "day_forecast"}
    screen.assert_awaited_once()
    awaited = screen.await_args
    assert awaited is not None
    assert awaited.args[2] == horoscope_intent.PERSONAL_DAILY_PROMPT


async def test_resume_without_pending_intent_leaves_current_state_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    await state.set_state(HoroscopeStates.waiting_for_birth_place)
    await state.update_data(birth_date="2000-01-01")
    screen = AsyncMock()
    monkeypatch.setattr(horoscope_intent, "show_screen", screen)

    resumed = await horoscope_intent.resume_horoscope_intent(cast("Message", object()), state)

    assert resumed is False
    assert await state.get_state() == HoroscopeStates.waiting_for_birth_place.state
    assert await state.get_data() == {"birth_date": "2000-01-01"}
    screen.assert_not_awaited()


async def test_unknown_horoscope_intent_is_rejected() -> None:
    state = _state()

    with pytest.raises(ValueError, match="unsupported horoscope intent"):
        await horoscope_intent.remember_horoscope_intent(state, "unknown")
