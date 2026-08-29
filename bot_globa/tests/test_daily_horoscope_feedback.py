"""Presentation contract for evening daily-horoscope feedback."""

from datetime import date

from app.bot.daily_feedback_handlers import _parse_feedback_callback
from app.bot.daily_horoscope import DAILY_FEEDBACK_PROMPT
from app.bot.keyboards import daily_feedback_keyboard
from app.domain.daily_horoscope import DailyHoroscopeFeedbackAnswer


def test_feedback_prompt_is_about_usefulness_not_prediction_accuracy() -> None:
    assert "Удалось ли сегодня воспользоваться прогнозом?" in DAILY_FEEDBACK_PROMPT
    assert "сбыл" not in DAILY_FEEDBACK_PROMPT.casefold()


def test_feedback_keyboard_is_one_tap_and_date_scoped() -> None:
    keyboard = daily_feedback_keyboard("2026-08-27")
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert [button.text for button in buttons] == ["Да, пригодился", "Нет, не пригодился"]
    assert [button.callback_data for button in buttons] == [
        "daily:feedback:useful:2026-08-27",
        "daily:feedback:not_useful:2026-08-27",
    ]
    assert all(
        button.callback_data is not None and len(button.callback_data.encode()) <= 64
        for button in buttons
    )


def test_feedback_callback_parser_rejects_stale_or_malformed_payloads() -> None:
    assert _parse_feedback_callback("daily:feedback:useful:2026-08-27") == (
        DailyHoroscopeFeedbackAnswer.USEFUL,
        date(2026, 8, 27),
    )
    assert _parse_feedback_callback("daily:feedback:not_useful:2026-08-27") == (
        DailyHoroscopeFeedbackAnswer.NOT_USEFUL,
        date(2026, 8, 27),
    )
    assert _parse_feedback_callback("daily:feedback:maybe:2026-08-27") is None
    assert _parse_feedback_callback("daily:feedback:useful:not-a-date") is None
