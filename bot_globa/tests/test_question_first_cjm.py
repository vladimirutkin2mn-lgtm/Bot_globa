"""Regression contract for the question-first private Numa entry flow."""

from app.bot import commands, core_handlers, persona_flows, texts
from app.bot.question_first import (
    daily_ritual_keyboard,
    question_first_menu_keyboard,
    question_first_onboarding_keyboard,
)


def _callbacks() -> list[str]:
    return [
        button.callback_data or ""
        for row in question_first_menu_keyboard().inline_keyboard
        for button in row
    ]


def test_question_first_entry_reuses_existing_safe_topic_routes() -> None:
    del commands  # importing commands installs the production CJM shell
    callbacks = _callbacks()

    assert callbacks[:5] == [
        "love:topic:love",
        "tarot:topic:general_forecast",
        "tarot:topic:decision",
        "psy:topic:repeating_pattern",
        "daily:personal",
    ]
    assert {"menu:love", "menu:tarot", "menu:psy", "menu:astro"} <= set(callbacks)
    assert "Что происходит между нами" in texts.MAIN_MENU or "О чём хочется спросить" in texts.MAIN_MENU


def test_question_first_shell_is_bound_to_existing_core_navigation() -> None:
    assert core_handlers.main_menu_keyboard is question_first_menu_keyboard
    assert core_handlers.onboarding_intro_keyboard is question_first_onboarding_keyboard
    assert core_handlers.daily_horoscope_keyboard is daily_ritual_keyboard
    assert question_first_onboarding_keyboard().inline_keyboard[0][0].text == "✨ Задать вопрос"


def test_deep_reading_packaging_matches_real_followup_entitlement() -> None:
    for flow in persona_flows.MVP_READING_FLOWS:
        assert "Быстрый взгляд" in flow.texts.locked
        assert "24 часа" in flow.texts.locked
        assert "до 3 уточняющих" in flow.texts.locked
        assert flow.texts.unlock_button.startswith("✨ Открыть глубокий разбор")

    assert "24 часа" in texts.PAYWALL
    assert "до 3 уточняющих" in texts.PAYWALL
    assert "один уточняющий" not in texts.PAYWALL


def test_daily_entry_is_framed_as_personal_ritual_not_another_generic_forecast() -> None:
    button = daily_ritual_keyboard().inline_keyboard[0][0]
    assert button.text == "✨ Что важно для меня сегодня"
    assert button.callback_data == "daily:personal"
