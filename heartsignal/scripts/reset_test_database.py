"""Reset the public schema of an explicitly named test database.

This helper exists only for CI isolation between Alembic validation and
PostgreSQL characterization tests. It refuses to run unless the target
database name ends with ``_test``.
"""

import asyncio
import os
from urllib.parse import urlparse

import asyncpg


def _asyncpg_dsn(value: str) -> str:
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


def _validated_test_dsn() -> str:
    raw = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not raw:
        raise RuntimeError("TEST_DATABASE_URL is required")
    dsn = _asyncpg_dsn(raw)
    database = urlparse(dsn).path.removeprefix("/")
    if not database.endswith("_test"):
        raise RuntimeError("refusing to reset a database without the _test suffix")
    return dsn


async def _reset() -> None:
    connection = await asyncpg.connect(_validated_test_dsn())
    try:
        await connection.execute("DROP SCHEMA public CASCADE")
        await connection.execute("CREATE SCHEMA public")
    finally:
        await connection.close()


def main() -> None:
    asyncio.run(_reset())


if __name__ == "__main__":
    main()
