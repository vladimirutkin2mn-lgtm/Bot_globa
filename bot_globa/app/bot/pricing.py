"""Customer-facing price labels resolved from the one authoritative billing catalog.

Every screen that shows a price — the paywall, the purchase list, the unlock button —
reads it from here, so a repriced SKU cannot say one number on one screen and another
number on the next.
"""

from app.config import Settings
from app.domain.billing import BillingCatalog
from app.domain.products import ProductCode, format_user_price
from app.providers.payments.base import BillingMarket


def telegram_stars_price(
    catalog: BillingCatalog,
    code: ProductCode,
    settings: Settings,
) -> int | None:
    """Return the sellable Star amount, or None when Stars cannot complete this purchase."""

    if not settings.telegram_stars_enabled:
        return None
    offer = catalog.resolve_product_offer(code, BillingMarket.TELEGRAM, "XTR")
    return offer.amount_minor if offer.amount_minor > 0 else None


def product_price_label(
    catalog: BillingCatalog,
    code: ProductCode,
    settings: Settings,
) -> str:
    """Render the local price, plus the Star amount when Stars are actually sellable."""

    local = catalog.resolve_product_offer(code, BillingMarket.RU, "RUB")
    label = format_user_price(local.amount_minor, local.currency)
    stars = telegram_stars_price(catalog, code, settings)
    return f"{label} / {stars} ⭐" if stars is not None else label
