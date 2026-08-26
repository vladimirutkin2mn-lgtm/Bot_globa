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


def test_main_menu_is_one_oracle_plus_explicit_practices() -> None:
    keyboard = main_menu_keyboard()
    callbacks = _callbacks(keyboard)
    labels = _labels(keyboard)
    legacy_topic_prefixes = ("love:topic:", "tarot:topic:", "psy:topic:")

    assert callbacks[:4] == [
        "oracle:auto",
        "oracle:tarot",
        "oracle:love",
        "oracle:astro",
    ]
    assert labels[:4] == [
        "✨ Рассказать Numa",
        "🔮 Таро",
        "💞 Любовный оракул",
        "🪐 Астрология",
    ]
    assert not any(callback.startswith(legacy_topic_prefixes) for callback in callbacks)


def test_more_menu_is_not_a_second_persona_storefront() -> None:
    callbacks = _callbacks(more_menu_keyboard())

    assert callbacks == ["menu:memory", "menu:balance", "menu:privacy", "menu:home"]
    assert "menu:psy" not in callbacks


def test_onboarding_starts_with_numa_not_a_topic_catalogue() -> None:
    assert _labels(onboarding_intro_keyboard()) == ["Начать"]
    assert "Что сегодня не даёт вам покоя?" in texts.MAIN_MENU
    assert "сама выберет способ разбора" in texts.MAIN_MENU


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
