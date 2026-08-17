from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from aiogram.types import Chat, InlineKeyboardMarkup, Message, User

from app.bot import refund_handlers
from app.bot.commands import BOT_COMMANDS


def test_private_command_menu_prefers_payment_over_refund() -> None:
    commands = {command.command: command.description for command in BOT_COMMANDS}

    assert commands["pay"] == "💳 Оплата"
    assert commands["paysupport"] == "💬 Помощь с оплатой"
    assert "refund" not in commands


async def test_pay_command_opens_existing_purchase_catalogue(monkeypatch: Any) -> None:
    telegram_user = User(id=42, is_bot=False, first_name="Анна", username="anna")
    message = Message(
        message_id=1,
        date=0,
        chat=Chat(id=42, type="private"),
        from_user=telegram_user,
        text="/pay",
    )
    state = SimpleNamespace()
    user = SimpleNamespace(id="user-id")
    onboarding = SimpleNamespace(current_user=AsyncMock(return_value=user))
    credits = SimpleNamespace(balance=AsyncMock(return_value=200))
    billing_settings = SimpleNamespace(reading_full_price_credits=100)
    billing_catalog = SimpleNamespace()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    shown = AsyncMock()

    async def allow_consent(*args: Any, **kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(refund_handlers, "ensure_consent", allow_consent)
    monkeypatch.setattr(refund_handlers, "products_keyboard", lambda *args, **kwargs: keyboard)
    monkeypatch.setattr(refund_handlers, "show_screen", shown)

    await refund_handlers.payment_menu(
        message,
        state,  # type: ignore[arg-type]
        onboarding,  # type: ignore[arg-type]
        credits,  # type: ignore[arg-type]
        billing_catalog,  # type: ignore[arg-type]
        billing_settings,  # type: ignore[arg-type]
        30,
    )

    credits.balance.assert_awaited_once_with("user-id")
    shown.assert_awaited_once()
    args, kwargs = shown.await_args
    assert "Доступно полных разборов: 2." in args[2]
    assert kwargs["reply_markup"] is keyboard
