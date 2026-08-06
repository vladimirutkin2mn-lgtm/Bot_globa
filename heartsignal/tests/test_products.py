from app.config import Settings
from app.domain.products import (
    PRODUCT_CATALOG_VERSION,
    ProductCatalog,
    ProductCode,
    format_minor,
)


def test_catalog_uses_server_settings_and_current_skus(settings: Settings) -> None:
    catalog = ProductCatalog(settings)

    assert tuple(product.code for product in catalog.all()) == tuple(ProductCode)
    assert {product.version for product in catalog.all()} == {PRODUCT_CATALOG_VERSION}

    single = catalog.get("reading_single")
    pack = catalog.get("reading_pack_5")
    natal = catalog.get("astrology_natal")
    forecast = catalog.get("astrology_forecast")
    monthly = catalog.get("subscription_monthly")

    assert single is not None and single.credits == settings.analysis_price_credits
    assert pack is not None and pack.credits == settings.analysis_price_credits * 5
    assert natal is not None and natal.amount_minor == single.amount_minor
    assert forecast is not None and forecast.amount_minor == single.amount_minor
    assert monthly is not None and monthly.credits == 30 and monthly.recurring is False
    assert all(product.receipt_label for product in catalog.all())
    assert catalog.get("unknown") is None


def test_legacy_callbacks_resolve_to_current_skus_without_reusing_old_version(
    settings: Settings,
) -> None:
    catalog = ProductCatalog(settings)

    legacy_single = catalog.get("analysis_single")
    legacy_pack = catalog.get("analysis_pack_5")

    assert legacy_single is not None
    assert legacy_single.code is ProductCode.READING_SINGLE
    assert legacy_single.version == PRODUCT_CATALOG_VERSION
    assert legacy_pack is not None
    assert legacy_pack.code is ProductCode.READING_PACK_5
    assert legacy_pack.version == PRODUCT_CATALOG_VERSION


def test_active_order_lookup_includes_current_and_pre_migration_coordinates() -> None:
    assert ProductCatalog.active_order_codes("reading_single") == (
        "reading_single",
        "analysis_single",
    )
    assert ProductCatalog.active_order_codes("analysis_pack_5") == (
        "reading_pack_5",
        "analysis_pack_5",
    )
    assert ProductCatalog.active_order_codes("astrology_natal") == ("astrology_natal",)


def test_historical_labels_are_available_without_reselling_legacy_skus(
    settings: Settings,
) -> None:
    catalog = ProductCatalog(settings)

    assert catalog.historical_label("analysis_single", 1) == "Один полный разбор"
    assert catalog.historical_label("analysis_pack_5", 1) == "Пять полных разборов"
    assert catalog.historical_label("reading_single", PRODUCT_CATALOG_VERSION) == (
        "Один полный разбор"
    )
    assert catalog.historical_label("analysis_single", PRODUCT_CATALOG_VERSION) is None


def test_minor_unit_formatting_never_uses_float() -> None:
    assert format_minor(19_900, "RUB") == "199,00 RUB"
