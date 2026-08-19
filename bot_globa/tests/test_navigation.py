"""Keyboard labels and callback contracts."""

from uuid import UUID

from aiogram.types import InlineKeyboardMarkup

from app.bot import horoscope_flow, texts
from app.bot.commands import BOT_COMMANDS
from app.bot.keyboards import (
    consent_keyboard,
    daily_horoscope_keyboard,
    daily_settings_keyboard,
    daily_timezone_keyboard,
    main_menu_keyboard,
    more_menu_keyboard,
    onboarding_intro_keyboard,
    readings_menu_keyboard,
)
from app.bot.persona_flows import TAROT_FLOW


def _buttons(keyboard: InlineKeyboardMarkup) -> dict[str, str | None]:
    return {button.text: button.callback_data for row in keyboard.inline_keyboard for button in row}


def test_main_menu_contains_required_sections() -> None:
    keyboard = main_menu_keyboard()
    assert [[button.text for button in row] for row in keyboard.inline_keyboard] == [
        ["💞 Что он / она чувствует?"],
        ["💌 Стоит ли мне написать?"],
        ["⚖️ Что выбрать: A или B?"],
        ["🔮 Что меня ждёт дальше?"],
        ["🌙 Почему это повторяется?"],
        ["🪐 Разобрать по натальной карте"],
        ["☀️ Сегодня для меня", "📚 Мои истории"],
        ["⋯ Ещё"],
    ]
    assert [[button.callback_data for button in row] for row in keyboard.inline_keyboard] == [
        ["love:topic:love"],
        ["love:topic:communication"],
        ["tarot:topic:decision"],
        ["tarot:topic:general_forecast"],
        ["psy:topic:repeating_pattern"],
        ["menu:astro"],
        ["menu:daily", "menu:readings"],
        ["menu:more"],
    ]


def test_entry_copy_starts_from_question_and_keeps_personas_reachable() -> None:
    assert onboarding_intro_keyboard().inline_keyboard[0][0].text == "Выбрать вопрос"
    assert "Что хотите понять прямо сейчас?" in texts.MAIN_MENU
    assert "Numa сама откроет подходящий способ разбора" in texts.MAIN_MENU

    more_labels = _buttons(more_menu_keyboard())
    assert more_labels["💞 Любовный оракул"] == "menu:love"
    assert more_labels["🔮 Таролог"] == "menu:tarot"
    assert more_labels["🌙 Мистический психолог"] == "menu:psy"
    assert more_labels["🪐 Астролог"] == "menu:astro"

    commands = {command.command: command.description for command in BOT_COMMANDS}
    assert {name: commands[name] for name in ("love", "tarot", "psy", "astro")} == {
        "love": "💞 Любовный оракул",
        "tarot": "🔮 Таролог",
        "psy": "🌙 Мистический психолог",
        "astro": "🪐 Астролог",
    }


def test_secondary_navigation_keeps_history_settings_privacy_and_personas_reachable() -> None:
    more = {button.callback_data for row in more_menu_keyboard().inline_keyboard for button in row}
    readings = {
        button.callback_data for row in readings_menu_keyboard().inline_keyboard for button in row
    }

    assert {
        "menu:love",
        "menu:tarot",
        "menu:psy",
        "menu:astro",
        "menu:memory",
        "menu:balance",
        "menu:privacy",
        "menu:home",
    } == more
    assert {
        "tarot:history",
        "love:history",
        "psy:history",
        "astro:history",
        "menu:home",
    } == readings
    assert [
        [button.text for button in row] for row in readings_menu_keyboard().inline_keyboard
    ] == [
        ["🔮 Таролог"],
        ["💞 Любовный оракул"],
        ["🌙 Мистический психолог"],
        ["🪐 Астролог"],
        ["← Назад в меню"],
    ]


def test_daily_horoscope_has_an_explicit_back_path_at_every_nested_step() -> None:
    daily = _buttons(daily_horoscope_keyboard())
    settings = _buttons(daily_settings_keyboard())
    timezone = _buttons(daily_timezone_keyboard())

    assert daily["← Назад в меню"] == "menu:home"
    assert daily["Настройки"] == "daily:settings"
    assert settings["← Назад к гороскопу"] == "menu:daily"
    assert timezone["← Назад к настройкам"] == "daily:settings"


def test_consent_returns_to_the_selected_persona() -> None:
    assert _buttons(consent_keyboard("tarot"))["← Назад"] == "menu:tarot"


def test_reading_flow_can_return_to_topics_and_history_hub() -> None:
    question = _buttons(TAROT_FLOW.question_keyboard())
    history = _buttons(TAROT_FLOW.history_keyboard([], page=0, has_next=False))
    full = _buttons(TAROT_FLOW.full_result_keyboard(UUID(int=1)))

    assert question["← Назад к темам"] == "tarot:new"
    assert history["← К моим разборам"] == "menu:readings"
    assert full["← К моим разборам"] == "menu:readings"


def test_astrologer_uses_back_routes_without_ambiguous_cancel_copy() -> None:
    question = _buttons(horoscope_flow.HOROSCOPE_FLOW.question_keyboard())
    birth_time = _buttons(horoscope_flow.birth_time_keyboard())
    place_choice = _buttons(horoscope_flow.place_choice_keyboard(["Москва"]))

    assert question["← Назад к темам"] == "astro:new"
    assert birth_time["← Назад к городу"] == "astro:place:retry"
    assert place_choice["← Назад к вводу города"] == "astro:place:retry"
    assert birth_time["← В главное меню"] == "astro:cancel"


def test_unimplemented_section_copy_is_exact() -> None:
    assert texts.COMING_LATER == "Раздел появится на следующем этапе."
