def test_private_command_menu_exposes_payment_terms() -> None:
    from app.bot.commands import BOT_COMMANDS

    commands = [command.command for command in BOT_COMMANDS]

    assert "terms" in commands
    assert commands.count("terms") == 1
