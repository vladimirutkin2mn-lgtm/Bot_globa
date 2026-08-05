"""Synchronize managed MVP persona records with the versioned registry."""

import asyncio

from app.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.services.persona_registry import PersonaRegistryService


async def _run() -> None:
    settings = get_settings()
    engine = create_engine(str(settings.database_url))
    try:
        result = await PersonaRegistryService(create_session_factory(engine)).sync_mvp_personas()
        print(
            "persona sync complete: "
            f"created={result.created} updated={result.updated} unchanged={result.unchanged}"
        )
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
