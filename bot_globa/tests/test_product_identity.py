"""Product identity and API metadata tests."""

from unittest.mock import MagicMock

from app.api.main import create_app
from app.config import Settings
from app.platform.identity import PRODUCT_IDENTITY


def test_product_identity_is_domain_neutral() -> None:
    assert PRODUCT_IDENTITY.repository_slug == "bot_globa"
    assert PRODUCT_IDENTITY.working_name == "Персональный AI-оракул"
    assert PRODUCT_IDENTITY.api_title == "Bot Globa API"
    assert PRODUCT_IDENTITY.legacy_baseline_name == "HeartSignal"


def test_api_uses_central_product_identity(settings: Settings) -> None:
    engine = MagicMock()
    app = create_app(settings, engine, register_telegram_webhook=False)

    assert app.title == PRODUCT_IDENTITY.api_title
    assert app.version == PRODUCT_IDENTITY.version
