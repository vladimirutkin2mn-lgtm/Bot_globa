from app.bot.commands import GROUP_COMMANDS


def test_visible_group_commands_match_the_compact_group_cjm() -> None:
    assert [(command.command, command.description) for command in GROUP_COMMANDS] == [
        ("compatibility", "💞 Совместимость"),
        ("duel", "⚔️ Астро-дуэль"),
        ("grouphelp", "✨ Другие игры"),
    ]
