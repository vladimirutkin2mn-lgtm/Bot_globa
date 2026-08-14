"""Migration safety for default-on daily-horoscope delivery settings."""

import asyncio
import os
import subprocess
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.postgres
_HEAD = "20260814_29"
_PARENT = "20260811_26"


async def _execute(url: str, schema: str, statement: str) -> None:
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


async def _scalar(url: str, schema: str, statement: str) -> object | None:
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.connect() as connection:
            return cast("object | None", await connection.scalar(text(statement)))
    finally:
        await engine.dispose()


def _database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required")
    return url


def _environment(url: str, schema: str) -> dict[str, str]:
    return {
        **os.environ,
        "DATABASE_URL": url,
        "MIGRATION_SCHEMA": schema,
        "TELEGRAM_BOT_TOKEN": "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "CONTENT_ENCRYPTION_KEY": "daily-horoscope-migration-key",
        "APP_ENV": "test",
    }


def _schema(url: str) -> str:
    schema = f"daily_horoscope_{uuid4().hex}"
    asyncio.run(_execute(url, "public", f'CREATE SCHEMA "{schema}"'))
    return schema


def test_daily_horoscope_migration_round_trip_when_empty() -> None:
    url = _database_url()
    schema = _schema(url)
    environment = _environment(url, schema)
    try:
        subprocess.run(("alembic", "upgrade", "head"), check=True, env=environment)
        assert asyncio.run(_scalar(url, schema, "SELECT version_num FROM alembic_version")) == _HEAD
        assert (
            asyncio.run(
                _scalar(
                    url,
                    schema,
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema=current_schema() "
                    "AND table_name='daily_horoscope_preferences'",
                )
            )
            == 1
        )
        subprocess.run(("alembic", "downgrade", _PARENT), check=True, env=environment)
        assert (
            asyncio.run(_scalar(url, schema, "SELECT version_num FROM alembic_version")) == _PARENT
        )
        subprocess.run(("alembic", "upgrade", "head"), check=True, env=environment)
    finally:
        asyncio.run(_execute(url, "public", f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def test_default_delivery_migration_enables_active_users_and_preserves_explicit_opt_outs() -> None:
    url = _database_url()
    schema = _schema(url)
    environment = _environment(url, schema)
    default_user = uuid4()
    evening_user = uuid4()
    on_request_user = uuid4()
    disabled_user = uuid4()
    deleted_user = uuid4()
    try:
        subprocess.run(("alembic", "upgrade", "20260813_28"), check=True, env=environment)
        asyncio.run(
            _execute(
                url,
                schema,
                "INSERT INTO users "
                "(id,telegram_user_id,first_name,privacy_status,deleted_at) VALUES "
                f"('{default_user}',975201,'Default','active',NULL),"
                f"('{evening_user}',975202,'Evening','active',NULL),"
                f"('{on_request_user}',975203,'On request','active',NULL),"
                f"('{disabled_user}',975204,'Disabled','active',NULL),"
                f"('{deleted_user}',NULL,NULL,'deleted',CURRENT_TIMESTAMP)",
            )
        )
        asyncio.run(
            _execute(
                url,
                schema,
                "INSERT INTO daily_horoscope_preferences "
                "(user_id,mode,next_delivery_at) VALUES "
                f"('{evening_user}','evening',CURRENT_TIMESTAMP),"
                f"('{on_request_user}','on_request',NULL),"
                f"('{disabled_user}','disabled',NULL)",
            )
        )

        subprocess.run(("alembic", "upgrade", "head"), check=True, env=environment)

        assert (
            asyncio.run(
                _scalar(
                    url,
                    schema,
                    f"SELECT mode FROM daily_horoscope_preferences WHERE user_id='{default_user}'",
                )
            )
            == "morning"
        )
        assert (
            asyncio.run(
                _scalar(
                    url,
                    schema,
                    f"SELECT mode FROM daily_horoscope_preferences WHERE user_id='{evening_user}'",
                )
            )
            == "morning"
        )
        # `on_request` was reachable only by tapping "Только по запросу", which answered
        # "Автоматическая доставка выключена". Turning it into a push would contradict
        # what the user was told, so it stays off with no schedule.
        assert (
            asyncio.run(
                _scalar(
                    url,
                    schema,
                    "SELECT mode FROM daily_horoscope_preferences "
                    f"WHERE user_id='{on_request_user}'",
                )
            )
            == "on_request"
        )
        assert (
            asyncio.run(
                _scalar(
                    url,
                    schema,
                    f"SELECT mode FROM daily_horoscope_preferences WHERE user_id='{disabled_user}'",
                )
            )
            == "disabled"
        )
        assert (
            asyncio.run(
                _scalar(
                    url,
                    schema,
                    "SELECT count(*) FROM daily_horoscope_preferences "
                    f"WHERE user_id='{deleted_user}'",
                )
            )
            == 0
        )
        assert (
            asyncio.run(
                _scalar(
                    url,
                    schema,
                    "SELECT next_delivery_at IS NOT NULL FROM daily_horoscope_preferences "
                    f"WHERE user_id='{default_user}'",
                )
            )
            is True
        )
        assert (
            asyncio.run(
                _scalar(
                    url,
                    schema,
                    "SELECT next_delivery_at IS NULL FROM daily_horoscope_preferences "
                    f"WHERE user_id='{on_request_user}'",
                )
            )
            is True
        )
        # A 'morning' column default would contradict the schedule check constraint, so the
        # revision drops the default rather than moving it.
        assert (
            asyncio.run(
                _scalar(
                    url,
                    schema,
                    "SELECT column_default FROM information_schema.columns "
                    f"WHERE table_schema='{schema}' "
                    "AND table_name='daily_horoscope_preferences' AND column_name='mode'",
                )
            )
            is None
        )
    finally:
        asyncio.run(_execute(url, "public", f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def test_daily_horoscope_migration_refuses_data_losing_downgrade() -> None:
    url = _database_url()
    schema = _schema(url)
    environment = _environment(url, schema)
    user_id = uuid4()
    try:
        subprocess.run(("alembic", "upgrade", "head"), check=True, env=environment)
        asyncio.run(
            _execute(
                url,
                schema,
                "INSERT INTO users (id,telegram_user_id,first_name,privacy_status) "
                f"VALUES ('{user_id}',975100,'Daily Migration','active')",
            )
        )
        asyncio.run(
            _execute(
                url,
                schema,
                "INSERT INTO daily_horoscope_preferences (user_id,mode) "
                f"VALUES ('{user_id}','disabled')",
            )
        )
        failed = subprocess.run(
            ("alembic", "downgrade", _PARENT),
            check=False,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert failed.returncode != 0
        assert "downgrade refused" in failed.stderr
        assert asyncio.run(_scalar(url, schema, "SELECT version_num FROM alembic_version")) == _HEAD
    finally:
        asyncio.run(_execute(url, "public", f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
