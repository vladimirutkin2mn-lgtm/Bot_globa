"""Versioned server-owned product catalog for oracle billing and presentation."""
# ruff: noqa: RUF001

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


class LegacyProductCode(StrEnum):
    """Accepted only as compatibility aliases or historical order coordinates."""

    ANALYSIS_SINGLE = "analysis_single"
    ANALYSIS_PACK_5 = "analysis_pack_5"


_LEGACY_ALIASES = {
    LegacyProductCode.ANALYSIS_SINGLE.value: ProductCode.READING_SINGLE,
    LegacyProductCode.ANALYSIS_PACK_5.value: ProductCode.READING_PACK_5,
}
_LEGACY_LABELS = {
    (LegacyProductCode.ANALYSIS_SINGLE.value, 1): "Один полный разбор",
    (LegacyProductCode.ANALYSIS_PACK_5.value, 1): "Пять полных разборов",
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
        reading_cost = settings.analysis_price_credits
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
                settings.product_reading_single_price_minor,
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
                settings.product_astrology_natal_credits,
                settings.product_astrology_natal_price_minor,
                settings.payment_currency,
            ),
            ProductCode.ASTROLOGY_FORECAST: Product(
                ProductCode.ASTROLOGY_FORECAST,
                PRODUCT_CATALOG_VERSION,
                "Персональный прогноз на неделю или месяц",
                "Персональный астрологический прогноз",
                settings.product_astrology_forecast_credits,
                settings.product_astrology_forecast_price_minor,
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
    def canonical_code(code: str | ProductCode | LegacyProductCode) -> ProductCode:
        """Map retired callback coordinates to current SKU without creating legacy orders."""

        value = code.value if isinstance(code, StrEnum) else code
        alias = _LEGACY_ALIASES.get(value)
        if alias is not None:
            return alias
        try:
            return ProductCode(value)
        except ValueError as exc:
            raise LookupError("unknown product") from exc

    def get(self, code: str | ProductCode | LegacyProductCode) -> Product | None:
        try:
            canonical = self.canonical_code(code)
        except LookupError:
            return None
        return self._products.get(canonical)

    def all(self) -> tuple[Product, ...]:
        return tuple(self._products.values())

    def historical_label(self, product_code: str, product_version: int) -> str | None:
        """Resolve labels for old receipts/history without making retired SKU sellable."""

        current = self.get(product_code)
        if current is not None and current.code.value == product_code:
            if current.version == product_version:
                return current.title
        return _LEGACY_LABELS.get((product_code, product_version))


def format_minor(amount: int, currency: str) -> str:
    """Format integer minor units without binary floating point."""

    return f"{amount // 100},{amount % 100:02d} {currency}"
