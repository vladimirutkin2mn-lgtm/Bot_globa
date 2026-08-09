"""Reset the public schema of an explicitly named test database.

This helper exists only for CI isolation between Alembic validation and
PostgreSQL characterization tests. It refuses to run unless the target
database name ends with ``_test``.
"""

import asyncio
import os
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def _validated_test_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("TEST_DATABASE_URL is required")
    database = urlparse(value).path.removeprefix("/")
    if not database.endswith("_test"):
        raise RuntimeError("refusing to reset a database without the _test suffix")
    return value


async def _reset() -> None:
    engine = create_async_engine(_validated_test_url())
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_reset())


if __name__ == "__main__":
    main()
