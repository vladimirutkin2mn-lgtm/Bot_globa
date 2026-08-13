import base64

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings


def production(**values: object) -> Settings:
    defaults: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql+asyncpg://u:p@db/x",
        "telegram_bot_token": SecretStr("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
        "content_encryption_key": SecretStr("test-only-strong-content-key-32-bytes"),
        "payment_public_base_url": "https://pay.example",
        "payment_provider": "stripe",
        "stripe_enabled": True,
        "stripe_secret_key": "sk_live_redacted",
        "stripe_webhook_secret": "whsec_redacted",
        "stripe_amount_reading_single_eur_minor": 400,
        "stripe_amount_reading_single_usd_minor": 500,
        "stripe_amount_reading_pack_5_eur_minor": 1800,
        "stripe_amount_reading_pack_5_usd_minor": 2200,
    }
    defaults.update(values)
    return Settings(**defaults)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "values",
    [
        {"billing_enabled": True, "payment_public_base_url": "http://pay.example"},
        {"billing_enabled": True, "payment_provider": "mock"},
        {"refunds_enabled": True},
        {"yookassa_recurring_enabled": True},
        {
            "stripe_enabled": True,
            "stripe_secret_key": "sk_test_redacted",
            "stripe_webhook_secret": "whsec_x",
        },
        {"subscriptions_enabled": True, "stripe_enabled": False},
    ],
)
def test_production_rejection_matrix(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        production(**values)


def test_kill_switch_blocks_new_work_not_ingress() -> None:
    settings = production(billing_enabled=True, billing_kill_switch=True)
    assert not settings.permits_new_checkout()
    assert not settings.permits_renewal()
    assert not settings.permits_refund()
    assert settings.permits_webhook_receipt()
    assert settings.permits_reconciliation()


def test_production_can_use_telegram_stars_as_its_only_gateway() -> None:
    settings = production(
        billing_enabled=True,
        payment_provider="production",
        stripe_enabled=False,
        stripe_secret_key="",
        stripe_webhook_secret="",
        telegram_stars_enabled=True,
        telegram_stars_amount_reading_single=75,
        telegram_stars_amount_reading_pack_5=300,
        telegram_stars_amount_subscription_monthly=450,
    )

    assert settings.permits_new_checkout()


@pytest.mark.parametrize(
    "key",
    [
        "",
        "change-me",
        "base64:not-valid!",
        "base64:" + base64.b64encode(b"short").decode(),
        "base64:" + base64.b64encode(b"x" * 64).decode(),
    ],
)
def test_production_rejects_unsafe_decoded_content_keys(key: str) -> None:
    with pytest.raises(ValidationError, match=r"content encryption key|strong"):
        production(content_encryption_key=SecretStr(key))


@pytest.mark.parametrize(
    "key",
    [
        "valid-test-text-key-material-with-32-bytes",
        "base64:" + base64.b64encode(bytes(range(32))).decode(),
    ],
)
def test_production_accepts_strong_content_keys(key: str) -> None:
    assert production(content_encryption_key=SecretStr(key)).app_env == "production"


def test_content_encryption_key_is_required() -> None:
    values = production().model_dump(exclude={"content_encryption_key"})
    with pytest.raises(ValidationError):
        Settings.model_validate(values)
