"""Versioned, server-authoritative billing offers and routing."""

from dataclasses import dataclass
from enum import StrEnum

from app.config import Settings
from app.domain.products import Product, ProductCatalog, ProductCode
from app.providers.payments.base import BillingMarket, PaymentProviderName


class PurchaseMode(StrEnum):
    ONE_TIME = "one_time"
    SUBSCRIPTION = "subscription"


@dataclass(frozen=True, slots=True)
class BillingOffer:
    product_code: ProductCode
    product_version: int
    purchase_mode: PurchaseMode
    title: str
    receipt_label: str
    active_order_codes: tuple[str, ...]
    credits: int
    market: BillingMarket
    provider: PaymentProviderName
    currency: str
    amount_minor: int
    price_reference: str
    billing_interval: str | None = None


class BillingCatalog:
    """Build every commercial route from one current product definition set."""

    def __init__(self, settings: Settings) -> None:
        self._products = ProductCatalog(settings)
        self._offers: dict[tuple[ProductCode, BillingMarket, str], BillingOffer] = {}
        for product in self._products.all():
            self._add(
                product,
                BillingMarket.RU,
                PaymentProviderName.YOOKASSA,
                "RUB",
                product.amount_minor,
                f"catalog:{product.code.value}:rub:v{product.version}",
            )
            for currency in ("EUR", "USD"):
                price_reference, amount_minor = _stripe_coordinates(
                    settings,
                    product.code,
                    currency,
                )
                pricing_code = _stripe_pricing_code(product.code)
                self._add(
                    product,
                    BillingMarket.INTERNATIONAL,
                    PaymentProviderName.STRIPE,
                    currency,
                    amount_minor if amount_minor is not None else 1,
                    price_reference
                    or f"unconfigured:{pricing_code.value}:{currency.lower()}:v{product.version}",
                )

    def _add(
        self,
        product: Product,
        market: BillingMarket,
        provider: PaymentProviderName,
        currency: str,
        amount_minor: int,
        price_reference: str,
    ) -> None:
        is_subscription = product.code is ProductCode.SUBSCRIPTION_MONTHLY
        self._offers[(product.code, market, currency)] = BillingOffer(
            product_code=product.code,
            product_version=product.version,
            purchase_mode=(PurchaseMode.SUBSCRIPTION if is_subscription else PurchaseMode.ONE_TIME),
            title=product.title,
            receipt_label=product.receipt_label,
            active_order_codes=self._products.active_order_codes(product.code),
            credits=product.credits,
            market=market,
            provider=provider,
            currency=currency,
            amount_minor=amount_minor,
            price_reference=price_reference,
            billing_interval="month" if is_subscription else None,
        )

    def resolve_product_offer(
        self,
        product_code: str | ProductCode,
        market: BillingMarket | str,
        currency: str,
    ) -> BillingOffer:
        """Resolve the exact route, canonicalizing retired client callback aliases."""

        try:
            canonical = self._products.canonical_code(product_code)
            key = (canonical, BillingMarket(market), currency)
        except (LookupError, ValueError) as exc:
            raise LookupError("unknown billing offer") from exc
        try:
            return self._offers[key]
        except KeyError as exc:
            raise LookupError("unsupported market/currency combination") from exc


def _stripe_pricing_code(product_code: ProductCode) -> ProductCode:
    if product_code in {ProductCode.ASTROLOGY_NATAL, ProductCode.ASTROLOGY_FORECAST}:
        return ProductCode.READING_SINGLE
    return product_code


def _stripe_coordinates(
    settings: Settings,
    product_code: ProductCode,
    currency: str,
) -> tuple[str, int | None]:
    """Reuse approved price coordinates until product-specific pricing is configured."""

    if currency == "EUR":
        single = (
            settings.stripe_price_analysis_single_eur,
            settings.stripe_amount_analysis_single_eur_minor,
        )
        pack = (
            settings.stripe_price_analysis_pack_5_eur,
            settings.stripe_amount_analysis_pack_5_eur_minor,
        )
        subscription = (
            settings.stripe_price_subscription_monthly_eur,
            settings.stripe_amount_subscription_monthly_eur_minor,
        )
    elif currency == "USD":
        single = (
            settings.stripe_price_analysis_single_usd,
            settings.stripe_amount_analysis_single_usd_minor,
        )
        pack = (
            settings.stripe_price_analysis_pack_5_usd,
            settings.stripe_amount_analysis_pack_5_usd_minor,
        )
        subscription = (
            settings.stripe_price_subscription_monthly_usd,
            settings.stripe_amount_subscription_monthly_usd_minor,
        )
    else:
        raise ValueError("Stripe catalog supports only EUR or USD")
    pricing_code = _stripe_pricing_code(product_code)
    if pricing_code is ProductCode.READING_PACK_5:
        return pack
    if pricing_code is ProductCode.SUBSCRIPTION_MONTHLY:
        return subscription
    return single
