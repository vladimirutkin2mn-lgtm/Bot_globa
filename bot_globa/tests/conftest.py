"""Shared test fixtures."""

import os

import pytest
from pydantic import SecretStr

from app.config import Settings

pytest_plugins = ("tests.payment_postgres_helpers",)

# Application modules expose an ASGI entry point at import time. Provide isolated,
# non-production values so test collection never depends on a developer's .env file.
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@db:5432/test",
        "TELEGRAM_BOT_TOKEN": "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "CONTENT_ENCRYPTION_KEY": "test-only-key",
    }
)


@pytest.fixture(autouse=True)
def bind_migration_safety_tests_to_current_head(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep historical downgrade guards anchored to the current repo head.

    Individual migration safety modules own their downgrade target, but their
    ``_HEAD`` assertion means "the currently deployable schema head". Binding
    that value here prevents every historical safety test from becoming stale
    when a later, unrelated migration is appended. ``test_schema_health`` still
    pins the exact expected head explicitly, so schema-head changes remain an
    intentional reviewed update.
    """

    module = request.module
    if "migration" not in module.__name__ or not hasattr(module, "_HEAD"):
        return

    from app.services.schema_health import expected_schema_heads

    expected_schema_heads.cache_clear()
    heads = expected_schema_heads()
    assert len(heads) == 1
    monkeypatch.setattr(module, "_HEAD", heads[0])


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/test",
        telegram_bot_token=SecretStr("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
        content_encryption_key=SecretStr("test-only-key"),
    )
