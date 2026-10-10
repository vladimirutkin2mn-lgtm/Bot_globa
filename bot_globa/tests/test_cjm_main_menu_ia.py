from aiogram.types import InlineKeyboardMarkup

from app.bot.commands import BOT_COMMANDS
from app.bot.keyboards import main_menu_keyboard, readings_menu_keyboard
from app.bot.persona_flows import MYSTICAL_PSYCHOLOGIST_FLOW


def _buttons(keyboard: InlineKeyboardMarkup) -> list[tuple[str, str | None]]:
    return [
        (button.text, button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
    ]


def test_main_menu_exposes_all_four_core_practices_and_honest_daily_label() -> None:
    buttons = _buttons(main_menu_keyboard())

    assert ("✨ Рассказать Numa", "oracle:auto") in buttons
    assert ("🔮 Таро", "oracle:tarot") in buttons
    assert ("💞 Любовный оракул", "oracle:love") in buttons
    assert ("🌙 Внутренний разбор", "menu:psy") in buttons
    assert ("🪐 Астрология", "oracle:astro") in buttons
    assert ("☀️ Гороскоп на сегодня", "menu:daily") in buttons
    assert all(label != "☀️ Сегодня для меня" for label, _ in buttons)


def test_reflection_practice_uses_one_consumer_name_across_navigation() -> None:
    command_labels = {command.command: command.description for command in BOT_COMMANDS}
    history_buttons = _buttons(readings_menu_keyboard())

    assert command_labels["psy"] == "🌙 Внутренний разбор"
    assert ("🌙 Внутренний разбор", "psy:history") in history_buttons
    assert MYSTICAL_PSYCHOLOGIST_FLOW.texts.welcome.startswith("🌙 Внутренний разбор")
