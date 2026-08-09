"""Migration coverage for paid oracle reading access linkage."""

import asyncio
import os
import subprocess
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.postgres
_HEAD = "20260806_24"
_PARENT = "20260805_17"


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
        "CONTENT_ENCRYPTION_KEY": "paid-reading-migration-key-material",
        "APP_ENV": "test",
    }


def _schema(url: str) -> str:
    schema = f"paid_reading_{uuid4().hex}"
    asyncio.run(_execute(url, "public", f'CREATE SCHEMA "{schema}"'))
    return schema


def test_paid_reading_migration_round_trip_when_unlinked() -> None:
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
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name='credit_transactions' "
                    "AND column_name='reading_id'",
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


def test_paid_reading_migration_refuses_downgrade_with_ledger_link() -> None:
    url = _database_url()
    schema = _schema(url)
    environment = _environment(url, schema)
    user_id, persona_id, reading_id, transaction_id = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        subprocess.run(("alembic", "upgrade", "head"), check=True, env=environment)
        asyncio.run(
            _execute(
                url,
                schema,
                "INSERT INTO users (id,telegram_user_id,first_name,privacy_status) "
                f"VALUES ('{user_id}',{uuid4().int % 10**12},'Paid Migration','active')",
            )
        )
        asyncio.run(
            _execute(
                url,
                schema,
                "INSERT INTO personas (id,code,display_name,prompt_version,schema_version,enabled) "
                f"VALUES ('{persona_id}','paid_tarot','Tarot','tarot-v1','result-v1',true)",
            )
        )
        asyncio.run(
            _execute(
                url,
                schema,
                "INSERT INTO readings "
                "(id,user_id,persona_id,topic,status,access_level,cost_units,engine_version,"
                "prompt_version,schema_version,generated_at) "
                f"VALUES ('{reading_id}','{user_id}','{persona_id}','decision','preview_ready',"
                "'preview',0,'reading-v1','tarot-v1','result-v1',now())",
            )
        )
        asyncio.run(
            _execute(
                url,
                schema,
                "INSERT INTO credit_transactions "
                "(id,user_id,type,amount,idempotency_key,reading_id) "
                f"VALUES ('{transaction_id}','{user_id}','spend',-1,'reading-full:{reading_id}',"
                f"'{reading_id}')",
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
