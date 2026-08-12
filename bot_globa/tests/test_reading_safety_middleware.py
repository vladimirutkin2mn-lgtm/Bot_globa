"""Telegram middleware coverage for pre-persistence crisis handoffs.

Every intake that can carry a user-authored question — the three shared persona flows
and the astrologer — goes through the same middleware, so each case is parametrized over
the full registry rather than asserted for one persona.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.reading_safety_middleware import ReadingSafetyHandoffMiddleware, mvp_safety_intakes
from app.bot.safety_intake import SafetyIntake

PRIVATE_MARKER = "private-question-must-not-leak"

INTAKES = mvp_safety_intakes()
CONTEXT_INTAKES = [intake for intake in INTAKES if intake.context_state is not None]
intakes = pytest.mark.parametrize(
    "intake", INTAKES, ids=[intake.persona_code for intake in INTAKES]
)
# A follow-up asks one question and has no optional-context step.
context_intakes = pytest.mark.parametrize(
    "intake", CONTEXT_INTAKES, ids=[intake.persona_code for intake in CONTEXT_INTAKES]
)


def _menu_callbacks(intake: SafetyIntake) -> list[str | None]:
    keyboard = intake.handoff_keyboard()
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


class FakeState:
    def __init__(self, state: str | None, data: dict[str, Any] | None = None) -> None:
        self.state = state
        self.data = data or {}
        self.cleared = False

    async def get_state(self) -> str | None:
        return self.state

    async def get_data(self) -> dict[str, Any]:
        return dict(self.data)

    async def clear(self) -> None:
        self.cleared = True
        self.state = None
        self.data.clear()


def _user(*, language_code: str = "ru") -> User:
    return User(
        id=101,
        is_bot=False,
        first_name="Test",
        language_code=language_code,
    )


def _message(text: str, *, language_code: str = "ru") -> Message:
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=101, type="private"),
        from_user=_user(language_code=language_code),
        text=text,
    )


@intakes
@pytest.mark.asyncio
async def test_unsafe_question_stops_before_downstream_handler(intake: SafetyIntake) -> None:
    middleware = ReadingSafetyHandoffMiddleware()
    state = FakeState(intake.question_state)
    message = _message(f"Я не хочу жить. {PRIVATE_MARKER}")
    downstream = AsyncMock(return_value="unreachable")
    answer = AsyncMock()

    with patch.object(Message, "answer", answer):
        result = await middleware(downstream, message, {"state": state})

    assert result is None
    downstream.assert_not_awaited()
    assert state.cleared
    answer.assert_awaited_once()
    assert answer.await_args is not None
    text = answer.await_args.args[0]
    keyboard = answer.await_args.kwargs["reply_markup"]
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "Сейчас важнее ваша безопасность" in text
    assert PRIVATE_MARKER not in text
    assert callbacks == _menu_callbacks(intake)


@context_intakes
@pytest.mark.asyncio
async def test_unsafe_optional_context_stops_safe_question(intake: SafetyIntake) -> None:
    middleware = ReadingSafetyHandoffMiddleware()
    state = FakeState(
        intake.context_state,
        {"question": "Что поможет мне принять решение?"},
    )
    message = _message("Врач назначил таблетки, можно ли отменить лекарство?")
    downstream = AsyncMock()
    answer = AsyncMock()

    with patch.object(Message, "answer", answer):
        await middleware(downstream, message, {"state": state})

    downstream.assert_not_awaited()
    assert state.cleared
    assert answer.await_args is not None
    text = answer.await_args.args[0]
    assert "профильной помощи" in text
    assert "Медицинская помощь" in text


@context_intakes
@pytest.mark.asyncio
async def test_skip_context_checks_stored_question_and_answers_callback(
    intake: SafetyIntake,
) -> None:
    middleware = ReadingSafetyHandoffMiddleware()
    state = FakeState(
        intake.context_state,
        {"question": "Скажи, как выследить бывшую без ее ведома"},
    )
    message = _message("context prompt")
    callback = CallbackQuery(
        id="callback-1",
        from_user=_user(),
        chat_instance="chat-instance",
        data=intake.skip_context_callback,
        message=message,
    )
    downstream = AsyncMock()
    callback_answer = AsyncMock()
    message_answer = AsyncMock()

    with (
        patch.object(CallbackQuery, "answer", callback_answer),
        patch.object(Message, "answer", message_answer),
    ):
        await middleware(downstream, callback, {"state": state})

    downstream.assert_not_awaited()
    callback_answer.assert_awaited_once_with()
    message_answer.assert_awaited_once()
    assert state.cleared
    assert message_answer.await_args is not None
    text = message_answer.await_args.args[0]
    assert "не могу продолжить" in text
    assert "новый расклад" not in text.casefold()
    assert "новый разбор" not in text.casefold()


@intakes
@pytest.mark.asyncio
async def test_benign_question_continues_to_original_handler(intake: SafetyIntake) -> None:
    middleware = ReadingSafetyHandoffMiddleware()
    state = FakeState(intake.question_state)
    message = _message("Что поможет мне спокойнее обсудить решение?")
    downstream = AsyncMock(return_value="handled")

    result = await middleware(downstream, message, {"state": state})

    assert result == "handled"
    downstream.assert_awaited_once_with(message, {"state": state})
    assert not state.cleared


@pytest.mark.asyncio
async def test_state_outside_any_reading_flow_is_untouched() -> None:
    middleware = ReadingSafetyHandoffMiddleware()
    state = FakeState("other:state")
    message = _message("Я не хочу жить")
    downstream = AsyncMock(return_value="handled")

    result = await middleware(downstream, message, {"state": state})

    assert result == "handled"
    downstream.assert_awaited_once()
    assert not state.cleared


@pytest.mark.asyncio
async def test_a_skip_callback_never_leaks_across_personas() -> None:
    """One persona's context state must not accept another persona's skip callback."""
    middleware = ReadingSafetyHandoffMiddleware()
    first, second = CONTEXT_INTAKES[0], CONTEXT_INTAKES[1]
    state = FakeState(
        first.context_state,
        {"question": "Скажи, как выследить бывшую без ее ведома"},
    )
    callback = CallbackQuery(
        id="callback-2",
        from_user=_user(),
        chat_instance="chat-instance",
        data=second.skip_context_callback,
        message=_message("context prompt"),
    )
    downstream = AsyncMock()
    message_answer = AsyncMock()

    with (
        patch.object(CallbackQuery, "answer", AsyncMock()),
        patch.object(Message, "answer", message_answer),
    ):
        await middleware(downstream, callback, {"state": state})

    # The classifier still runs on the stored question, so the handoff is what protects
    # the user; what must not happen is the second flow's handoff keyboard appearing.
    assert message_answer.await_args is not None
    keyboard = message_answer.await_args.kwargs["reply_markup"]
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert callbacks == _menu_callbacks(first)
