import pytest

from app.config import Settings
from app.domain.billing import BillingCatalog
from app.domain.products import PRODUCT_CATALOG_VERSION, ProductCode
from app.providers.payments.base import BillingMarket, PaymentProviderName


def test_authoritative_routes(settings: Settings) -> None:
    catalog = BillingCatalog(settings)
    ru = catalog.resolve_product_offer("reading_single", BillingMarket.RU, "RUB")
    assert ru.provider is PaymentProviderName.YOOKASSA
    assert ru.product_code is ProductCode.READING_SINGLE
    assert ru.product_version == PRODUCT_CATALOG_VERSION
    assert ru.receipt_label == "Полный персональный разбор"

    for currency in ("EUR", "USD"):
        offer = catalog.resolve_product_offer(
            "reading_pack_5",
            BillingMarket.INTERNATIONAL,
            currency,
        )
        assert offer.provider is PaymentProviderName.STRIPE
        assert offer.product_code is ProductCode.READING_PACK_5

    with pytest.raises(LookupError):
        catalog.resolve_product_offer("reading_single", BillingMarket.RU, "USD")


def test_an_unknown_product_code_is_refused_rather_than_guessed(settings: Settings) -> None:
    catalog = BillingCatalog(settings)

    with pytest.raises(LookupError):
        catalog.resolve_product_offer("analysis_single", BillingMarket.RU, "RUB")


def test_astrology_skus_share_approved_single_reading_price_until_pricing_changes(
    settings: Settings,
) -> None:
    catalog = BillingCatalog(settings)
    single = catalog.resolve_product_offer(
        "reading_single",
        BillingMarket.INTERNATIONAL,
        "EUR",
    )
    natal = catalog.resolve_product_offer(
        "astrology_natal",
        BillingMarket.INTERNATIONAL,
        "EUR",
    )
    forecast = catalog.resolve_product_offer(
        "astrology_forecast",
        BillingMarket.INTERNATIONAL,
        "EUR",
    )

    assert natal.amount_minor == single.amount_minor
    assert forecast.amount_minor == single.amount_minor
    assert natal.price_reference == single.price_reference
    assert forecast.price_reference == single.price_reference
    assert natal.receipt_label != forecast.receipt_label


def test_stripe_uses_currency_specific_expected_amounts(settings: Settings) -> None:
    configured = settings.model_copy(
        update={
            "stripe_amount_reading_single_eur_minor": 411,
            "stripe_amount_reading_single_usd_minor": 577,
        }
    )
    catalog = BillingCatalog(configured)
    eur = catalog.resolve_product_offer("reading_single", BillingMarket.INTERNATIONAL, "EUR")
    usd = catalog.resolve_product_offer("reading_single", BillingMarket.INTERNATIONAL, "USD")
    rub = catalog.resolve_product_offer("reading_single", BillingMarket.RU, "RUB")
    assert (eur.amount_minor, usd.amount_minor, rub.amount_minor) == (411, 577, 19_900)
