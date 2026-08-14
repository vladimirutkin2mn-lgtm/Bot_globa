"""Regression coverage for returning from provider checkout to payment methods."""

from aiogram.types import InlineKeyboardMarkup

from app.bot.keyboards import (
    checkout_creating_keyboard,
    checkout_keyboard,
    checkout_unavailable_keyboard,
    receipt_contact_keyboard,
)
from app.bot.subscription_handlers import subscription_checkout_keyboard

BACK_LABEL = "← Назад к способам оплаты"


def _callbacks(keyboard: InlineKeyboardMarkup) -> dict[str, str | None]:
    return {
        button.text: button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    }


def test_one_time_provider_steps_return_to_same_product_methods() -> None:
    product_code = "reading_pack_5"
    expected = f"credits:buy:{product_code}"

    keyboards = (
        checkout_keyboard("https://provider.test/pay", product_code),
        checkout_creating_keyboard(product_code),
        checkout_unavailable_keyboard(product_code, "INTERNATIONAL", "EUR"),
        receipt_contact_keyboard(product_code),
    )

    for keyboard in keyboards:
        assert _callbacks(keyboard)[BACK_LABEL] == expected


def test_subscription_checkout_returns_to_subscription_methods() -> None:
    callbacks = _callbacks(subscription_checkout_keyboard("https://provider.test/subscription"))

    assert callbacks[BACK_LABEL] == "credits:buy:subscription_monthly"
