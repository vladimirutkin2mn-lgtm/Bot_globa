"""Keyboard labels and callback contracts."""

from app.bot import texts
from app.bot.commands import BOT_COMMANDS
from app.bot.keyboards import (
    main_menu_keyboard,
    more_menu_keyboard,
    onboarding_intro_keyboard,
    readings_menu_keyboard,
)


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
        ["Главное меню"],
    ]


def test_unimplemented_section_copy_is_exact() -> None:
    assert texts.COMING_LATER == "Раздел появится на следующем этапе."
