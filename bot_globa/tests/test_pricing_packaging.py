"""Customer pricing is expressed as reading outcomes, never as the internal entitlement ledger."""

import inspect
from datetime import UTC, datetime
from uuid import uuid4

from aiogram.types import InlineKeyboardMarkup

from app.bot import refund_handlers, subscription_handlers, texts
from app.bot.keyboards import more_menu_keyboard, products_keyboard
from app.bot.pricing import product_price_label, reading_count_label, subscription_offer_terms
from app.bot.telegram_stars_handlers import payment_support_text
from app.config import Settings
from app.domain.billing import BillingCatalog
from app.domain.products import ProductCode
from app.services.refund_service import RefundPurchaseView, RefundView


def _button_texts(keyboard: InlineKeyboardMarkup) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


def test_direct_paywall_leads_with_deep_reading_and_catalog_price(
    settings: Settings,
) -> None:
    catalog = BillingCatalog(settings)
    keyboard = products_keyboard(catalog, settings, resume_callback="love:unlock:reading-id")
    buttons = _button_texts(keyboard)

    expected_price = product_price_label(catalog, ProductCode.READING_SINGLE, settings)
    assert buttons[0] == f"✨ Открыть глубокий разбор — {expected_price}"
    assert buttons[1].startswith("🔮 5 глубоких разборов — ")
    assert "кредит" not in " ".join(buttons).casefold()


def test_generic_purchase_screen_sells_deep_readings_instead_of_ledger_units(
    settings: Settings,
) -> None:
    catalog = BillingCatalog(settings)
    keyboard = products_keyboard(catalog, settings)
    buttons = _button_texts(keyboard)

    assert buttons[0].startswith("✨ 1 глубокий разбор — ")
    assert buttons[1].startswith("🔮 5 глубоких разборов — ")
    assert "кредит" not in " ".join(buttons).casefold()


def test_subscription_exposes_real_reading_count_period_and_renewal(settings: Settings) -> None:
    subscription_settings = settings.model_copy(
        update={
            "subscriptions_enabled": True,
            "product_subscription_monthly_credits": 12,
        }
    )
    catalog = BillingCatalog(subscription_settings)
    buttons = _button_texts(products_keyboard(catalog, subscription_settings))

    assert any(button.startswith("🌙 Numa Plus · 12 разборов/мес — ") for button in buttons)
    assert subscription_offer_terms(catalog, subscription_settings) == (
        "1 месяц · 12 разборов · с автопродлением"
    )
    assert subscription_handlers.subscription_choice_text(catalog, subscription_settings) == (
        "Numa Plus: 1 месяц · 12 разборов · с автопродлением.\n"
        "Выберите способ оплаты. Провайдер покажет сумму и подтвердит условия до оплаты."
    )


def test_reading_count_label_uses_russian_plural_forms() -> None:
    assert reading_count_label(1) == "1 разбор"
    assert reading_count_label(2) == "2 разбора"
    assert reading_count_label(5) == "5 разборов"
    assert reading_count_label(11) == "11 разборов"
    assert reading_count_label(21) == "21 разбор"


def test_customer_copy_does_not_expose_balance_or_credit_ledger_vocabulary() -> None:
    customer_copy = " ".join(
        (
            texts.PAYWALL,
            texts.CHECKOUT_STALE_BUTTON,
            texts.BALANCE,
            texts.PRIVACY_INFO,
            texts.DELETE_ALL_PROMPT,
            payment_support_text(),
            " ".join(_button_texts(more_menu_keyboard())),
        )
    ).casefold()

    assert "кредит" not in customer_copy
    assert "баланс" not in customer_copy
    assert texts.BALANCE == "💳 Покупки"
    assert "глубокий разбор по этому вопросу" in texts.PAYWALL.casefold()


def test_subscription_cancellation_copy_keeps_value_in_seans_units() -> None:
    source = inspect.getsource(subscription_handlers)

    assert "начисленные кредиты" not in source.casefold()
    assert "уже доступные сеансы сохраняются" in source.casefold()


def test_refund_menu_hides_internal_product_codes_and_ledger_units() -> None:
    purchase = RefundPurchaseView(
        payment_order_id=uuid4(),
        provider="stripe",
        product_code="reading_pack_5",
        refundable_credits=5,
        refund_amount_minor=449,
        currency="EUR",
        completed_at=datetime.now(UTC),
    )

    buttons = _button_texts(refund_handlers._purchase_keyboard((purchase,)))
    visible = " ".join(buttons).casefold()

    assert buttons[0] == "Пакет полных разборов · 4.49 EUR"
    assert "reading_pack_5" not in visible
    assert "кредит" not in visible
    assert " кр." not in visible


def test_refund_history_uses_access_status_instead_of_credit_units() -> None:
    refund = RefundView(
        id=uuid4(),
        payment_order_id=uuid4(),
        provider="stripe",
        status="credits_reserved",
        amount_minor=99,
        currency="EUR",
        credit_units=1,
        failure_code=None,
        created_at=datetime.now(UTC),
    )

    history = refund_handlers._history_text((refund,))
    source = inspect.getsource(refund_handlers)

    assert "0.99 EUR · доступ зарезервирован" in history
    assert "кредит" not in history.casefold()
    assert "кредит" not in source.casefold()
