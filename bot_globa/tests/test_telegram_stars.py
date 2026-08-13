"""Telegram Stars catalog, payload, refund, and presentation contracts."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from aiogram.types import (
    StarTransaction,
    StarTransactions,
    TransactionPartnerUser,
)
from aiogram.types import (
    User as TelegramUser,
)
from pydantic import SecretStr, ValidationError

from app.bot.keyboards import payment_market_keyboard
from app.bot.subscription_handlers import subscription_market_keyboard
from app.bot.telegram_stars_handlers import payment_support_text, payment_terms_text
from app.config import Settings
from app.domain.billing import BillingCatalog
from app.providers.payments.refund_gateway import CreateRefund
from app.providers.payments.telegram_stars import TelegramStarsGateway
from app.services.telegram_stars_service import parse_stars_payload, stars_payload


def configured(**changes: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "database_url": "postgresql+asyncpg://u:p@db/x",
        "telegram_bot_token": SecretStr("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
        "content_encryption_key": SecretStr("test-only-strong-content-key-32-bytes"),
        "telegram_stars_enabled": True,
        "subscriptions_enabled": True,
        "telegram_stars_amount_reading_single": 75,
        "telegram_stars_amount_reading_pack_5": 300,
        "telegram_stars_amount_subscription_monthly": 450,
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"telegram_stars_amount_reading_single": 0},
        {"telegram_stars_amount_reading_pack_5": 0},
        {"telegram_stars_amount_subscription_monthly": 0},
    ],
)
def test_enabled_stars_require_explicit_prices(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        configured(**changes)


def test_one_time_stars_do_not_require_a_subscription_price() -> None:
    settings = configured(
        subscriptions_enabled=False,
        telegram_stars_amount_subscription_monthly=0,
    )

    assert settings.telegram_stars_enabled


def test_terms_and_payment_support_are_available_without_external_links() -> None:
    terms = payment_terms_text(configured())
    support = payment_support_text()

    assert "принимаете эти условия" in terms
    assert "/refund" in terms
    assert "/refund_status" in support
    assert "http" not in terms + support


def test_catalog_exposes_xtr_without_changing_existing_routes() -> None:
    catalog = BillingCatalog(configured())
    stars = catalog.resolve_product_offer("astrology_natal", "TELEGRAM", "XTR")
    rub = catalog.resolve_product_offer("astrology_natal", "RU", "RUB")

    assert stars.provider.value == "telegram_stars"
    assert stars.amount_minor == 75
    assert stars.currency == "XTR"
    assert stars.price_reference == "catalog:reading_single:xtr:v2"
    assert rub.provider.value == "yookassa"


def test_stars_payload_is_compact_and_strict() -> None:
    order_id = uuid4()
    payload = stars_payload(order_id)

    assert len(payload.encode()) <= 128
    assert parse_stars_payload(payload) == order_id
    assert parse_stars_payload(payload + "00") is None
    assert parse_stars_payload("foreign:payload") is None


def test_payment_choice_shows_stars_and_card_routes_together() -> None:
    keyboard = payment_market_keyboard("reading_single", telegram_stars_enabled=True)
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]

    assert callbacks == [
        "credits:stars:reading_single",
        "credits:offer:reading_single:RU:RUB",
        "credits:offer:reading_single:INTERNATIONAL:EUR",
        "credits:offer:reading_single:INTERNATIONAL:USD",
        "menu:balance",
    ]


def test_subscription_choice_shows_every_enabled_route_together() -> None:
    settings = configured(
        yookassa_enabled=True,
        yookassa_recurring_enabled=True,
        stripe_enabled=True,
    )
    keyboard = subscription_market_keyboard(settings)
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]

    assert callbacks == [
        "credits:stars:subscription_monthly",
        "credits:offer:subscription_monthly:RU:RUB",
        "credits:offer:subscription_monthly:INTERNATIONAL:EUR",
        "credits:offer:subscription_monthly:INTERNATIONAL:USD",
        "menu:balance",
    ]


class FakeStarsBot:
    def __init__(self) -> None:
        self.refunded: list[tuple[int, str]] = []
        self.edited: list[tuple[int, str, bool]] = []
        user = TelegramUser(id=42, is_bot=False, first_name="Stars")
        partner = TransactionPartnerUser(transaction_type="invoice_payment", user=user)
        self.transactions = StarTransactions(
            transactions=[
                StarTransaction(
                    id="charge-one",
                    amount=-75,
                    date=datetime.now(UTC),
                    receiver=partner,
                )
            ]
        )

    async def refund_star_payment(
        self,
        user_id: int,
        telegram_payment_charge_id: str,
        request_timeout: int | None = None,
    ) -> bool:
        self.refunded.append((user_id, telegram_payment_charge_id))
        return True

    async def get_star_transactions(
        self,
        offset: int | None = None,
        limit: int | None = None,
        request_timeout: int | None = None,
    ) -> StarTransactions:
        return self.transactions

    async def edit_user_star_subscription(
        self,
        user_id: int,
        telegram_payment_charge_id: str,
        is_canceled: bool,
        request_timeout: int | None = None,
    ) -> bool:
        self.edited.append((user_id, telegram_payment_charge_id, is_canceled))
        return True


async def test_stars_refund_uses_full_original_charge_and_distinct_ledger_identity() -> None:
    bot = FakeStarsBot()
    gateway = TelegramStarsGateway(bot, timeout_seconds=5, reconciliation_pages=2)
    request = CreateRefund(
        user_id=uuid4(),
        refund_request_id=uuid4(),
        provider_payment_id="charge-one",
        amount_minor=75,
        currency="XTR",
        reason="requested_by_customer",
        idempotency_key="refund:test",
        provider_customer_id="42",
    )

    created = await gateway.create_refund(request)
    fetched = await gateway.fetch_refund(created.provider_refund_id)
    await gateway.set_subscription_canceled(42, "charge-one", is_canceled=True)

    assert bot.refunded == [(42, "charge-one")]
    assert created.provider_payment_id == "charge-one"
    assert created.provider_refund_id == "stars-refund:charge-one"
    assert fetched == created
    assert not gateway.refund_capabilities.partial_refunds
    assert bot.edited == [(42, "charge-one", True)]
