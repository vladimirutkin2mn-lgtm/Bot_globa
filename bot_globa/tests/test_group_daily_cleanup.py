from app.bot import group_handlers, group_social_handlers, group_viral_handlers
from app.bot.commands import GROUP_COMMANDS
from app.bot.group_daily_cleanup import group_cosmic_weather


def test_public_group_commands_keep_only_distinct_daily_rituals() -> None:
    commands = {item.command: item.description for item in GROUP_COMMANDS}

    assert "card" in commands
    assert commands["advice"] == "🪐 Космическая погода"
    assert "chat" not in commands
    assert "forecast" not in commands


def test_duplicate_daily_handlers_are_not_registered() -> None:
    callbacks = [handler.callback for handler in group_handlers.router.message.handlers]

    assert group_handlers.group_chat_archetype not in callbacks
    assert group_social_handlers.group_forecast not in callbacks
    assert group_viral_handlers.group_advice not in callbacks
    assert group_cosmic_weather in callbacks


def test_party_menu_keeps_vibe_but_removes_evening_forecast() -> None:
    keyboard = group_handlers._party_menu_keyboard()
    buttons = [
        (button.text, button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert ("🔥 Вайб вечера", "group:party:vibe") in buttons
    assert all(callback != "social:party:evening" for _text, callback in buttons)
    assert all(text != "🌙 Прогноз на вечер" for text, _callback in buttons)


def test_group_help_matches_clean_daily_surface() -> None:
    help_text = group_handlers.GROUP_HELP

    assert "🪐 /advice — космическая погода" in help_text
    assert "/chat" not in help_text
    assert "/forecast" not in help_text
