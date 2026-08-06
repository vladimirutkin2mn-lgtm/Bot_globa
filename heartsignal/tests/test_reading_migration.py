"""PostgreSQL migration safety for the independent Reading domain."""

import asyncio
import os
import subprocess
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.postgres
_HEAD = "20260806_21"
_PARENT = "20260805_16"


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
            return cast(object | None, await connection.scalar(text(statement)))
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
        "CONTENT_ENCRYPTION_KEY": "reading-migration-test-key-material",
        "APP_ENV": "test",
    }


def _schema(url: str) -> str:
    schema = f"reading_{uuid4().hex}"
    asyncio.run(_execute(url, "public", f'CREATE SCHEMA "{schema}"'))
    return schema


def test_reading_migration_round_trip_when_empty() -> None:
    url = _database_url()
    schema = _schema(url)
    environment = _environment(url, schema)
    try:
        subprocess.run(("alembic", "upgrade", "head"), check=True, env=environment)
        assert asyncio.run(_scalar(url, schema, "SELECT version_num FROM alembic_version")) == _HEAD
        assert asyncio.run(_scalar(url, schema, "SELECT count(*) FROM personas")) == 0
        assert asyncio.run(_scalar(url, schema, "SELECT count(*) FROM readings")) == 0
        subprocess.run(("alembic", "downgrade", _PARENT), check=True, env=environment)
        assert (
            asyncio.run(_scalar(url, schema, "SELECT version_num FROM alembic_version")) == _PARENT
        )
        subprocess.run(("alembic", "upgrade", "head"), check=True, env=environment)
    finally:
        asyncio.run(_execute(url, "public", f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def test_reading_migration_refuses_downgrade_with_live_state() -> None:
    url = _database_url()
    schema = _schema(url)
    environment = _environment(url, schema)
    user_id, persona_id, reading_id = uuid4(), uuid4(), uuid4()
    try:
        subprocess.run(("alembic", "upgrade", "head"), check=True, env=environment)
        asyncio.run(
            _execute(
                url,
                schema,
                "INSERT INTO users (id,telegram_user_id,first_name,privacy_status) "
                f"VALUES ('{user_id}',{uuid4().int % 10**12},'Migration','active')",
            )
        )
        asyncio.run(
            _execute(
                url,
                schema,
                "INSERT INTO personas "
                "(id,code,display_name,prompt_version,schema_version,enabled) "
                f"VALUES ('{persona_id}','tarot_reader','Tarot','tarot-v1','result-v1',true)",
            )
        )
        asyncio.run(
            _execute(
                url,
                schema,
                "INSERT INTO readings "
                "(id,user_id,persona_id,topic,status,access_level,cost_units,engine_version,"
                "prompt_version,schema_version) "
                f"VALUES ('{reading_id}','{user_id}','{persona_id}','decision','draft','none',"
                "0,'reading-v1','tarot-v1','result-v1')",
            )
        )
        failed = subprocess.run(
            ("alembic", "downgrade", _PARENT),
            env=environment,
            capture_output=True,
            text=True,
        )
        assert failed.returncode != 0
        assert "downgrade refused" in failed.stderr
        assert asyncio.run(_scalar(url, schema, "SELECT version_num FROM alembic_version")) == _HEAD
        assert asyncio.run(_scalar(url, schema, "SELECT count(*) FROM readings")) == 1
    finally:
        asyncio.run(_execute(url, "public", f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
