"""Keyboard labels and callback contracts."""

from app.bot import texts
from app.bot.keyboards import main_menu_keyboard


def test_main_menu_contains_required_sections() -> None:
    keyboard = main_menu_keyboard()
    assert [row[0].text for row in keyboard.inline_keyboard] == [
        "🔮 Таролог",
        "💞 Любовный оракул",
        "🌙 Мистический психолог",
        "🪐 Астролог",
        "🧠 Память",
        texts.BALANCE,
        texts.PRIVACY,
    ]
    assert [row[0].callback_data for row in keyboard.inline_keyboard] == [
        "menu:tarot",
        "menu:love",
        "menu:psy",
        "menu:astro",
        "menu:memory",
        "menu:balance",
        "menu:privacy",
    ]


def test_unimplemented_section_copy_is_exact() -> None:
    assert texts.COMING_LATER == "Раздел появится на следующем этапе."
