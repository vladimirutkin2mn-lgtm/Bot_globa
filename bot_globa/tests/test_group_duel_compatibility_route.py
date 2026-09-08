"""Regression coverage for continuing the exact duel pair into compatibility."""

import pytest

from app.bot.group_social_handlers import _duel_result_keyboard


def test_duel_result_keeps_group_compatibility_and_private_love_separate() -> None:
    keyboard = _duel_result_keyboard("numa_test_bot", 101, 202)

    assert len(keyboard.inline_keyboard) == 2
    group_button = keyboard.inline_keyboard[0][0]
    private_button = keyboard.inline_keyboard[1][0]

    assert group_button.text == "💞 Проверить совместимость"
    assert group_button.callback_data == "gc:a:101:101:202"
    assert private_button.text == "💬 Разобрать отношения лично"
    assert private_button.url == "https://t.me/numa_test_bot?start=love"


def test_duel_compatibility_callback_stays_within_telegram_limit() -> None:
    first = 9_223_372_036_854_775_807
    second = 9_223_372_036_854_775_806

    keyboard = _duel_result_keyboard(None, first, second)
    callback_data = keyboard.inline_keyboard[0][0].callback_data

    assert callback_data is not None
    assert len(callback_data.encode()) <= 64
    assert len(keyboard.inline_keyboard) == 1


@pytest.mark.parametrize("first,second", [(0, 2), (1, 0), (7, 7)])
def test_duel_compatibility_refuses_invalid_pair(first: int, second: int) -> None:
    with pytest.raises(ValueError):
        _duel_result_keyboard("numa_test_bot", first, second)
