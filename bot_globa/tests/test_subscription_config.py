import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.domain.billing import BillingCatalog


def base(**changes: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "database_url": "postgresql+asyncpg://u:p@db/x",
        "telegram_bot_token": SecretStr("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
        "content_encryption_key": SecretStr("test-only-strong-content-key-32-bytes"),
        "stripe_amount_subscription_monthly_eur_minor": 990,
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("amount", [0, 49])
def test_subscription_amount_below_the_provider_minimum_is_rejected(amount: int) -> None:
    """Stripe refuses anything under 0.50, so an unsellable price never reaches it."""

    with pytest.raises(ValidationError):
        base(stripe_amount_subscription_monthly_eur_minor=amount)


def test_catalog_uses_exact_configured_subscription_amount() -> None:
    settings = base()
    offer = BillingCatalog(settings).resolve_product_offer(
        "subscription_monthly", "INTERNATIONAL", "EUR"
    )
    assert offer.amount_minor == 990
    assert offer.price_reference == "catalog:subscription_monthly:eur:v2"
    assert offer.billing_interval == "month"


def test_every_supported_currency_is_sellable_without_provider_setup() -> None:
    """Prices travel inline with the checkout, so no currency depends on dashboard work."""

    catalog = BillingCatalog(base())
    for currency in ("EUR", "USD"):
        offer = catalog.resolve_product_offer("subscription_monthly", "INTERNATIONAL", currency)
        assert offer.amount_minor >= 50
        assert offer.price_reference == f"catalog:subscription_monthly:{currency.lower()}:v2"
