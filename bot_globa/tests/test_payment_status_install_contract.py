from app.bot import core_handlers
from app.bot.commands import BOT_COMMANDS
from app.bot.payment_status_handlers import balance_with_payment_status


def test_payment_status_handler_replaces_passive_balance_handler() -> None:
    callbacks = [handler.callback for handler in core_handlers.router.callback_query.handlers]
    assert core_handlers.balance_screen not in callbacks
    assert callbacks.count(balance_with_payment_status) == 1


def test_payment_commands_remain_available() -> None:
    commands = {item.command for item in BOT_COMMANDS}
    assert {"pay", "paysupport"} <= commands
