"""Regression contract for the question-first private Numa entry flow."""

from app.bot import commands, core_handlers, keyboards, persona_flows, texts
from app.bot.question_first import (
    _question_first_consent_keyboard,
    _question_first_privacy_keyboard,
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


def test_question_first_entry_routes_are_intent_specific() -> None:
    assert commands.BOT_COMMANDS[0].command == "start"
    callbacks = _callbacks()

    assert callbacks[:5] == [
        "qf:go:love",
        "qf:go:future",
        "qf:go:decision",
        "qf:go:pattern",
        "menu:daily",
    ]
    assert {"menu:love", "menu:tarot", "menu:psy", "menu:astro"} <= set(callbacks)
    assert "О чём хочется спросить" in texts.MAIN_MENU


def test_question_first_consent_preserves_the_chosen_intent() -> None:
    consent = _question_first_consent_keyboard("decision")
    assert consent.inline_keyboard[0][0].callback_data == "qf:consent:decision"
    assert consent.inline_keyboard[1][0].callback_data == "qf:privacy:decision"

    privacy = _question_first_privacy_keyboard("decision")
    assert privacy.inline_keyboard[-1][0].callback_data == "qf:privacy-back:decision"


def test_question_first_shell_is_canonical_for_all_navigation() -> None:
    core_bindings = vars(core_handlers)
    keyboard_bindings = vars(keyboards)
    assert core_bindings["main_menu_keyboard"] is question_first_menu_keyboard
    assert core_bindings["onboarding_intro_keyboard"] is question_first_onboarding_keyboard
    assert core_bindings["daily_horoscope_keyboard"] is daily_ritual_keyboard
    assert keyboard_bindings["main_menu_keyboard"] is question_first_menu_keyboard
    assert keyboard_bindings["onboarding_intro_keyboard"] is question_first_onboarding_keyboard
    assert keyboard_bindings["daily_horoscope_keyboard"] is daily_ritual_keyboard
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


def test_daily_entry_starts_with_free_ritual_before_personalization() -> None:
    main_daily = question_first_menu_keyboard().inline_keyboard[4][0]
    assert main_daily.text == "🪐 Что важно для меня сегодня?"
    assert main_daily.callback_data == "menu:daily"

    personal = daily_ritual_keyboard().inline_keyboard[0][0]
    assert personal.text == "✨ Что важно для меня сегодня"
    assert personal.callback_data == "daily:personal"
