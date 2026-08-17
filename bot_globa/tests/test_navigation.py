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
        ["💞 Любовный оракул"],
        ["🔮 Таролог"],
        ["🌙 Мистический психолог"],
        ["🪐 Астролог"],
        ["☀️ Гороскоп на сегодня", "📚 Мои разборы"],
        ["⋯ Ещё"],
    ]
    assert [[button.callback_data for button in row] for row in keyboard.inline_keyboard] == [
        ["menu:love"],
        ["menu:tarot"],
        ["menu:psy"],
        ["menu:astro"],
        ["menu:daily", "menu:readings"],
        ["menu:more"],
    ]


def test_entry_copy_explains_the_four_distinct_personas() -> None:
    assert onboarding_intro_keyboard().inline_keyboard[0][0].text == "Выбрать персонажа"
    assert "Любовный оракул — чувства, притяжение и динамика отношений" in texts.MAIN_MENU
    assert "Таролог — расклад Таро на ваш вопрос" in texts.MAIN_MENU
    assert "трёх карт" not in texts.MAIN_MENU
    assert "Мистический психолог — разбор через метафоры и архетипы" in texts.MAIN_MENU
    assert "Астролог — натальная карта" in texts.MAIN_MENU

    commands = {command.command: command.description for command in BOT_COMMANDS}
    assert {name: commands[name] for name in ("love", "tarot", "psy", "astro")} == {
        "love": "💞 Любовный оракул",
        "tarot": "🔮 Таролог",
        "psy": "🌙 Мистический психолог",
        "astro": "🪐 Астролог",
    }


def test_secondary_navigation_keeps_history_settings_and_privacy_reachable() -> None:
    more = {button.callback_data for row in more_menu_keyboard().inline_keyboard for button in row}
    readings = {
        button.callback_data for row in readings_menu_keyboard().inline_keyboard for button in row
    }

    assert {"menu:memory", "menu:balance", "menu:privacy", "menu:home"} == more
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


def test_consent_screen_never_traps_the_user() -> None:
    assert _buttons(consent_keyboard("tarot"))["← Назад в меню"] == "menu:home"


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
