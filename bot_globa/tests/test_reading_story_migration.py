"""Migration safety for encrypted manual reading stories."""

import asyncio
import os
import subprocess
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.postgres
_HEAD = "20260911_39"
_PARENT = "20260909_38"


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
        "CONTENT_ENCRYPTION_KEY": "reading-story-migration-key",
        "APP_ENV": "test",
    }


def _schema(url: str) -> str:
    schema = f"reading_story_{uuid4().hex}"
    asyncio.run(_execute(url, "public", f'CREATE SCHEMA "{schema}"'))
    return schema


def test_reading_story_migration_round_trip_when_empty() -> None:
    url = _database_url()
    schema = _schema(url)
    environment = _environment(url, schema)
    try:
        subprocess.run(("alembic", "upgrade", "head"), check=True, env=environment)
        assert asyncio.run(_scalar(url, schema, "SELECT version_num FROM alembic_version")) == _HEAD
        for table_name in (
            "reading_stories",
            "reading_story_private_content",
            "reading_story_links",
        ):
            assert (
                asyncio.run(
                    _scalar(
                        url,
                        schema,
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema=current_schema() "
                        f"AND table_name='{table_name}'",
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


def test_reading_story_migration_refuses_live_story_downgrade() -> None:
    url = _database_url()
    schema = _schema(url)
    environment = _environment(url, schema)
    user_id = uuid4()
    story_id = uuid4()
    try:
        subprocess.run(("alembic", "upgrade", "head"), check=True, env=environment)
        asyncio.run(
            _execute(
                url,
                schema,
                "INSERT INTO users (id,telegram_user_id,first_name,privacy_status) "
                f"VALUES ('{user_id}',{uuid4().int % 10**12},'Story Migration','active')",
            )
        )
        asyncio.run(
            _execute(
                url,
                schema,
                f"INSERT INTO reading_stories (id,user_id) VALUES ('{story_id}','{user_id}')",
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
        assert asyncio.run(_scalar(url, schema, "SELECT count(*) FROM reading_stories")) == 1
    finally:
        asyncio.run(_execute(url, "public", f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
