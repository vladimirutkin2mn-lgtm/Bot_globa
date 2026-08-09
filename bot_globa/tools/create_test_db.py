#!/usr/bin/env python3
"""Create the local test database if it does not exist yet.

Deliberately talks to PostgreSQL directly instead of `docker compose exec`, so the test
path never needs a `.env` file — see the warning in the Makefile.

Lives in `tools/` rather than `scripts/` because `scripts/` is part of the linted and
type-checked CI surface; this is local developer plumbing, not application code.
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg

USER = os.environ.get("DB_USER", "bot_globa")
PASSWORD = os.environ.get("DB_PASSWORD", USER)
HOST = os.environ.get("DB_HOST", "localhost")
PORT = int(os.environ.get("DB_PORT", "5432"))
TEST_DB = os.environ.get("TEST_DB_NAME", "bot_globa_test")


RESET = os.environ.get("RESET") == "1"


async def main() -> int:
    conn = await asyncpg.connect(
        user=USER, password=PASSWORD, host=HOST, port=PORT, database="postgres"
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
            print(f"created database {TEST_DB}")
            return 0
        if not RESET:
            return 0
    finally:
        await conn.close()

    # RESET=1: drop every object in the public schema, keeping the database itself.
    # Guarded by CONFIRM=yes in the Makefile — never reachable by accident.
    target = await asyncpg.connect(
        user=USER, password=PASSWORD, host=HOST, port=PORT, database=TEST_DB
    )
    try:
        await target.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        print(f"reset schema in {TEST_DB}")
    finally:
        await target.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
