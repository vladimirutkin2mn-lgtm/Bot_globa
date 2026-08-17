from datetime import date, time

from aiogram.types import InlineKeyboardMarkup

from app.bot import group_handlers
from app.bot.commands import GROUP_COMMANDS
from app.bot.group_compatibility_handlers import (
    _context_keyboard,
    compatibility_entry,
    compatibility_second,
)
from app.bot.group_compatibility_ux import (
    _join_first_keyboard,
    _join_second_keyboard,
    _join_self_keyboard,
    _lobby_keyboard,
    compatibility_entry_ux,
    compatibility_lobby_action,
)
from app.domain.birth_profile import BirthProfileInput
from app.domain.natal_chart import NatalChartResult
from app.domain.synastry import CompatibilityContext, calculate_synastry
from app.services.natal_chart import AstronomyEngineNatalChartCalculator


def _chart(day: date, hour: int) -> NatalChartResult:
    profile = BirthProfileInput(
        birth_date=day,
        birth_time=time(hour, 0),
        birth_place="Greenwich",
        timezone="UTC",
        latitude=51.4769,
        longitude=0.0,
        utc_offset_minutes=0,
    )
    return AstronomyEngineNatalChartCalculator().calculate(profile)


def _callback_data(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def test_synastry_is_symmetric_bounded_and_contextual() -> None:
    first = _chart(date(1991, 4, 8), 10)
    second = _chart(date(1993, 8, 17), 18)

    love = calculate_synastry(first, second, CompatibilityContext.LOVE)
    reverse = calculate_synastry(second, first, CompatibilityContext.LOVE)
    work = calculate_synastry(first, second, CompatibilityContext.WORK)

    assert love == reverse
    assert 38 <= love.overall <= 96
    assert 38 <= love.scores.attraction <= 96
    assert 38 <= love.scores.communication <= 96
    assert 38 <= love.scores.emotional <= 96
    assert 38 <= love.scores.stability <= 96
    assert work.scores == love.scores
    assert work.context is CompatibilityContext.WORK
    assert love.strongest
    assert love.weakest
    assert love.verdict


def test_group_compatibility_uses_callback_only_person_selection() -> None:
    message_callbacks = [handler.callback for handler in group_handlers.router.message.handlers]
    callback_callbacks = [
        handler.callback for handler in group_handlers.router.callback_query.handlers
    ]

    assert group_handlers.compatibility not in message_callbacks
    assert compatibility_entry not in message_callbacks
    assert compatibility_second not in message_callbacks
    assert compatibility_entry_ux in message_callbacks
    assert compatibility_lobby_action in callback_callbacks


def test_lobby_and_join_callbacks_are_explicit_and_compact() -> None:
    assert _callback_data(_lobby_keyboard(123)) == ["gcu:m:123", "gcu:o:123"]
    assert _callback_data(_join_self_keyboard(123)) == ["gcu:j:123"]
    assert _callback_data(_join_first_keyboard(123)) == ["gcu:f:123"]
    assert _callback_data(_join_second_keyboard(123, 456)) == ["gcu:s:123:456"]


def test_context_callbacks_fit_telegram_limit_for_large_user_ids() -> None:
    huge = 4_503_599_627_370_495
    callbacks = _callback_data(_context_keyboard(huge, huge - 1, huge - 2))

    assert len(callbacks) == 4
    assert all(len(value.encode()) <= 64 for value in callbacks)
    assert {value.split(":")[2] for value in callbacks} == {"l", "f", "w", "t"}


def test_group_command_opens_lobby_without_reply_contract() -> None:
    command = next(command for command in GROUP_COMMANDS if command.command == "compatibility")

    assert command.description == "💞 Совместимость участников"
    assert command.is_ephemeral is True
    assert "совместимость по натальной карте" in group_handlers.GROUP_HELP
    assert "лобби" in group_handlers.GROUP_HELP
    assert "reply-команд" not in group_handlers.GROUP_HELP
    assert "/with" not in [command.command for command in GROUP_COMMANDS]
