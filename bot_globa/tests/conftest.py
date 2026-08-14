"""Shared test fixtures."""

import os
import re

import pytest
from pydantic import SecretStr

from app.config import Settings

pytest_plugins = ("tests.payment_postgres_helpers",)
_REVISION_ID = re.compile(r"^\d{8}_\d+$")

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

    Individual migration safety modules own their downgrade target, while module-level
    revision constants containing ``HEAD`` mean "the currently deployable schema head".
    Binding only those revision-shaped constants prevents historical safety tests from
    becoming stale when a later migration is appended. ``test_schema_health`` is not a
    migration module and still pins the exact expected head explicitly, so schema-head
    changes remain an intentional reviewed update.
    """

    module = request.module
    if "migration" not in module.__name__:
        return
    head_constants = [
        name
        for name, value in vars(module).items()
        if name.startswith("_")
        and "HEAD" in name
        and isinstance(value, str)
        and _REVISION_ID.fullmatch(value) is not None
    ]
    if not head_constants:
        return

    from app.services.schema_health import expected_schema_heads

    expected_schema_heads.cache_clear()
    heads = expected_schema_heads()
    assert len(heads) == 1
    for name in head_constants:
        monkeypatch.setattr(module, name, heads[0])


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/test",
        telegram_bot_token=SecretStr("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
        content_encryption_key=SecretStr("test-only-key"),
    )
