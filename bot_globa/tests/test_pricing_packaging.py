"""Customer pricing is expressed as readings, never as the internal entitlement ledger."""

from aiogram.types import InlineKeyboardMarkup

from app.bot import texts
from app.bot.keyboards import more_menu_keyboard, products_keyboard
from app.bot.pricing import product_price_label
from app.config import Settings
from app.domain.billing import BillingCatalog
from app.domain.products import ProductCode


def _button_texts(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


def test_direct_paywall_leads_with_the_concrete_reading_and_catalog_price(
    settings: Settings,
) -> None:
    catalog = BillingCatalog(settings)
    keyboard = products_keyboard(catalog, settings, resume_callback="love:unlock:reading-id")
    buttons = _button_texts(keyboard)

    expected_price = product_price_label(catalog, ProductCode.READING_SINGLE, settings)
    assert buttons[0] == f"Открыть этот разбор — {expected_price}"
    assert buttons[1].startswith("Пакет · 5 полных разборов — ")
    assert "кредит" not in " ".join(buttons).casefold()


def test_generic_purchase_screen_sells_outcomes_instead_of_ledger_units(settings: Settings) -> None:
    catalog = BillingCatalog(settings)
    keyboard = products_keyboard(catalog, settings)
    buttons = _button_texts(keyboard)

    assert buttons[0].startswith("1 полный разбор — ")
    assert buttons[1].startswith("Пакет · 5 полных разборов — ")
    assert "кредит" not in " ".join(buttons).casefold()


def test_subscription_is_presented_as_a_monthly_reading_product(settings: Settings) -> None:
    subscription_settings = settings.model_copy(update={"subscriptions_enabled": True})
    catalog = BillingCatalog(subscription_settings)
    buttons = _button_texts(products_keyboard(catalog, subscription_settings))

    assert any(button.startswith("Подписка · 30 разборов в месяц — ") for button in buttons)


def test_customer_copy_does_not_expose_balance_or_credit_ledger_vocabulary() -> None:
    customer_copy = " ".join(
        (
            texts.PAYWALL,
            texts.CHECKOUT_STALE_BUTTON,
            texts.BALANCE,
            texts.PRIVACY_INFO,
            texts.DELETE_ALL_PROMPT,
            " ".join(_button_texts(more_menu_keyboard())),
        )
    ).casefold()

    assert "кредит" not in customer_copy
    assert "баланс" not in customer_copy
    assert texts.BALANCE == "💳 Покупки"
    assert "полный разбор по этому вопросу" in texts.PAYWALL.casefold()
