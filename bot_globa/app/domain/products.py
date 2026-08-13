"""Versioned server-owned product catalog for oracle billing and presentation."""

from dataclasses import dataclass
from enum import StrEnum

from app.config import Settings

PRODUCT_CATALOG_VERSION = 2


class ProductCode(StrEnum):
    READING_SINGLE = "reading_single"
    READING_PACK_5 = "reading_pack_5"
    ASTROLOGY_NATAL = "astrology_natal"
    ASTROLOGY_FORECAST = "astrology_forecast"
    SUBSCRIPTION_MONTHLY = "subscription_monthly"


# These are the three choices a person buys. Astrology-specific SKUs remain in the
# authoritative catalog for receipts and reconciliation, but showing them beside the
# same one-reading offer would make the Telegram paywall look like five different
# products.
READING_PURCHASE_CODES = (
    ProductCode.READING_SINGLE,
    ProductCode.READING_PACK_5,
    ProductCode.SUBSCRIPTION_MONTHLY,
)


# An order keeps the label it was created with, so a later catalog reprice or rename
# cannot change what an existing order is completed or refunded as.
_HISTORICAL_LABELS = {
    (ProductCode.SUBSCRIPTION_MONTHLY.value, 1): "Месячная подписка",
}


@dataclass(frozen=True, slots=True)
class Product:
    code: ProductCode
    version: int
    title: str
    receipt_label: str
    credits: int
    amount_minor: int
    currency: str
    recurring: bool = False


class ProductCatalog:
    """Expose current sellable products while preserving historical display labels."""

    def __init__(self, settings: Settings) -> None:
        reading_cost = settings.reading_price_credits
        single_amount = settings.product_reading_single_price_minor
        subscription_title = (
            "Месячная подписка с автопродлением"
            if settings.subscriptions_enabled
            else "Месячный запас кредитов (без автопродления)"
        )
        self._products = {
            ProductCode.READING_SINGLE: Product(
                ProductCode.READING_SINGLE,
                PRODUCT_CATALOG_VERSION,
                "Один полный разбор",
                "Полный персональный разбор",
                reading_cost,
                single_amount,
                settings.payment_currency,
            ),
            ProductCode.READING_PACK_5: Product(
                ProductCode.READING_PACK_5,
                PRODUCT_CATALOG_VERSION,
                "Пять полных разборов",
                "Пакет из пяти персональных разборов",
                reading_cost * 5,
                settings.product_reading_pack_5_price_minor,
                settings.payment_currency,
            ),
            ProductCode.ASTROLOGY_NATAL: Product(
                ProductCode.ASTROLOGY_NATAL,
                PRODUCT_CATALOG_VERSION,
                "Персональный натальный профиль",
                "Персональный натальный профиль",
                reading_cost,
                single_amount,
                settings.payment_currency,
            ),
            ProductCode.ASTROLOGY_FORECAST: Product(
                ProductCode.ASTROLOGY_FORECAST,
                PRODUCT_CATALOG_VERSION,
                "Персональный прогноз на неделю или месяц",
                "Персональный астрологический прогноз",
                reading_cost,
                single_amount,
                settings.payment_currency,
            ),
            ProductCode.SUBSCRIPTION_MONTHLY: Product(
                ProductCode.SUBSCRIPTION_MONTHLY,
                PRODUCT_CATALOG_VERSION,
                subscription_title,
                "Месячная подписка персонального AI-оракула",
                settings.product_subscription_monthly_credits,
                settings.product_subscription_monthly_price_minor,
                settings.payment_currency,
                recurring=settings.subscriptions_enabled,
            ),
        }

    @staticmethod
    def canonical_code(code: str | ProductCode) -> ProductCode:
        value = code.value if isinstance(code, StrEnum) else code
        try:
            return ProductCode(value)
        except ValueError as exc:
            raise LookupError("unknown product") from exc

    @classmethod
    def active_order_codes(cls, code: str | ProductCode) -> tuple[str, ...]:
        """Find an unfinished order for this SKU before creating another one."""

        return (cls.canonical_code(code).value,)

    def get(self, code: str | ProductCode) -> Product | None:
        try:
            canonical = self.canonical_code(code)
        except LookupError:
            return None
        return self._products.get(canonical)

    def all(self) -> tuple[Product, ...]:
        return tuple(self._products.values())

    def historical_label(self, product_code: str, product_version: int) -> str | None:
        """Resolve old order labels without making retired SKU sellable."""

        current = self.get(product_code)
        if (
            current is not None
            and current.code.value == product_code
            and current.version == product_version
        ):
            return current.title
        return _HISTORICAL_LABELS.get((product_code, product_version))


def format_minor(amount: int, currency: str) -> str:
    """Format integer minor units without binary floating point."""

    return f"{amount // 100},{amount % 100:02d} {currency}"


def format_user_price(amount: int, currency: str) -> str:
    """Render a compact customer-facing amount without binary floating point."""

    whole, fraction = divmod(amount, 100)
    number = str(whole) if fraction == 0 else f"{whole},{fraction:02d}"
    symbol = {"RUB": "₽", "EUR": "€", "USD": "$"}.get(currency)
    return f"{number} {symbol or currency}"
