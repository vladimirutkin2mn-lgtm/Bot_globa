"""Deployment policy, managed database URL, and release-command tests."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.cli.release import asyncpg_dsn
from app.config import Settings
from app.db.session import normalize_async_database_url
from app.deployment import (
    DeploymentSettings,
    validate_telegram_webhook,
    validate_telegram_worker,
)


def test_managed_postgres_urls_select_asyncpg() -> None:
    assert normalize_async_database_url("postgres://u:p@db/name") == (
        "postgresql+asyncpg://u:p@db/name"
    )
    assert normalize_async_database_url("postgresql://u:p@db/name") == (
        "postgresql+asyncpg://u:p@db/name"
    )
    assert normalize_async_database_url("postgresql+asyncpg://u:p@db/name") == (
        "postgresql+asyncpg://u:p@db/name"
    )
    assert asyncpg_dsn("postgres://u:p@db/name") == "postgresql://u:p@db/name"
    assert asyncpg_dsn("postgresql+asyncpg://u:p@db/name") == "postgresql://u:p@db/name"
    assert asyncpg_dsn("postgresql://u:p@db/name") == "postgresql://u:p@db/name"


def test_webhook_policy_accepts_local_and_strong_production_urls(settings: Settings) -> None:
    local = settings.model_copy(
        update={
            "telegram_webhook_url": "http://localhost:8000/telegram/webhook",
            "telegram_webhook_secret": SecretStr("local-secret"),
        }
    )
    validate_telegram_webhook(local)

    production = settings.model_copy(
        update={
            "app_env": "production",
            "telegram_webhook_url": "https://example.com/telegram/webhook",
            "telegram_webhook_secret": SecretStr("a" * 32),
        }
    )
    validate_telegram_webhook(production)


@pytest.mark.parametrize(
    ("url", "secret"),
    [
        ("https://example.com/wrong", "a" * 32),
        ("https://example.com/telegram/webhook?token=x", "a" * 32),
        ("http://example.com/telegram/webhook", "a" * 32),
        ("https://example.com/telegram/webhook", "short"),
        ("https://example.com/telegram/webhook", "unsafe secret value"),
    ],
)
def test_production_webhook_policy_fails_closed(settings: Settings, url: str, secret: str) -> None:
    configured = settings.model_copy(
        update={
            "app_env": "production",
            "telegram_webhook_url": url,
            "telegram_webhook_secret": SecretStr(secret),
        }
    )
    with pytest.raises(ValueError):
        validate_telegram_webhook(configured)


def test_telegram_worker_lease_covers_configured_llm_budget(settings: Settings) -> None:
    webhook_settings = settings.model_copy(
        update={
            "telegram_webhook_url": "https://example.com/telegram/webhook",
            "telegram_webhook_secret": SecretStr("a" * 32),
        }
    )
    validate_telegram_worker(
        webhook_settings,
        DeploymentSettings(telegram_update_lease_seconds=300),
    )
    with pytest.raises(ValueError, match="shorter than"):
        validate_telegram_worker(
            webhook_settings,
            DeploymentSettings(telegram_update_lease_seconds=120),
        )


def test_telegram_worker_requires_webhook_mode(settings: Settings) -> None:
    with pytest.raises(ValueError, match="requires webhook mode"):
        validate_telegram_worker(settings, DeploymentSettings())


def test_deployment_settings_reject_unbounded_values() -> None:
    with pytest.raises(ValidationError):
        DeploymentSettings(telegram_webhook_max_bytes=0)
    with pytest.raises(ValidationError):
        DeploymentSettings(telegram_update_lease_seconds=29)
    with pytest.raises(ValidationError):
        DeploymentSettings(telegram_update_retry_base_seconds=0)
    with pytest.raises(ValidationError):
        DeploymentSettings(telegram_update_max_attempts=101)
    with pytest.raises(ValidationError):
        DeploymentSettings(telegram_worker_idle_seconds=0)
    with pytest.raises(ValidationError):
        DeploymentSettings(maintenance_batch_size=10_001)


def test_production_compose_loads_the_approved_stars_rollout_after_secrets() -> None:
    root = Path(__file__).parents[1]
    values = dict(
        line.split("=", 1)
        for line in (root / "production.public.env").read_text().splitlines()
        if line and not line.startswith("#")
    )
    compose = (root / "docker-compose.prod.yml").read_text()

    assert values["BILLING_KILL_SWITCH"] == "false"
    assert values["TELEGRAM_STARS_ENABLED"] == "true"
    assert values["TELEGRAM_STARS_AMOUNT_READING_SINGLE"] == "40"
    assert values["TELEGRAM_STARS_AMOUNT_READING_PACK_5"] == "200"
    assert values["TELEGRAM_STARS_AMOUNT_SUBSCRIPTION_MONTHLY"] == "280"
    assert values["SUBSCRIPTIONS_ENABLED"] == "true"
    assert compose.count("      - .env.prod\n      - production.public.env") == 5
