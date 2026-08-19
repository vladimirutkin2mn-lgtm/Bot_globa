from uuid import UUID

from aiogram.types import InlineKeyboardMarkup

from app.bot import texts
from app.bot.keyboards import (
    daily_horoscope_keyboard,
    main_menu_keyboard,
    more_menu_keyboard,
    onboarding_intro_keyboard,
)
from app.bot.persona_flow import FOLLOWUP_BUTTON
from app.bot.persona_flows import TAROT_FLOW


def _callbacks(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def _labels(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


def test_main_menu_is_question_first() -> None:
    keyboard = main_menu_keyboard()
    callbacks = _callbacks(keyboard)
    labels = _labels(keyboard)

    assert callbacks[:5] == [
        "love:topic:love",
        "love:topic:communication",
        "tarot:topic:decision",
        "tarot:topic:general_forecast",
        "psy:topic:repeating_pattern",
    ]
    assert labels[:5] == [
        "💞 Что он / она чувствует?",
        "💌 Стоит ли мне написать?",
        "⚖️ Что выбрать: A или B?",
        "🔮 Что меня ждёт дальше?",
        "🌙 Почему это повторяется?",
    ]
    assert "menu:love" not in callbacks
    assert "menu:tarot" not in callbacks


def test_persona_choice_still_exists_in_more_menu() -> None:
    callbacks = _callbacks(more_menu_keyboard())
    assert {"menu:love", "menu:tarot", "menu:psy", "menu:astro"}.issubset(callbacks)


def test_onboarding_starts_from_question_not_persona() -> None:
    assert _labels(onboarding_intro_keyboard()) == ["Выбрать вопрос"]
    assert "Что хотите понять прямо сейчас?" in texts.MAIN_MENU


def test_preview_upgrade_is_framed_as_deep_reading() -> None:
    reading_id = UUID("00000000-0000-0000-0000-000000000123")
    keyboard = TAROT_FLOW.result_keyboard(reading_id, "99 ₽")
    paywall = texts.PAYWALL.casefold()

    assert _labels(keyboard)[0] == "✨ Открыть глубокий разбор — 99 ₽"
    assert "быстром взгляде" in paywall
    assert "глубокий разбор" in paywall


def test_paid_result_makes_session_continuity_visible() -> None:
    reading_id = UUID("00000000-0000-0000-0000-000000000123")
    labels = _labels(TAROT_FLOW.full_result_keyboard(reading_id))
    assert labels[0] == FOLLOWUP_BUTTON
    assert "Numa помнит" in labels[0]


def test_daily_screen_has_personal_and_question_paths() -> None:
    callbacks = _callbacks(daily_horoscope_keyboard())
    labels = _labels(daily_horoscope_keyboard())
    assert "daily:personal" in callbacks
    assert "tarot:topic:general_forecast" in callbacks
    assert "✨ Что сегодня важно именно для меня?" in labels
