"""PostgreSQL coverage for idempotent managed persona synchronization."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.reading_models import Persona
from app.services.persona_registry import PersonaRegistryService

pytestmark = pytest.mark.postgres


async def test_sync_creates_four_personas_and_is_idempotent(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    service = PersonaRegistryService(payment_db)

    first = await service.sync_mvp_personas()
    second = await service.sync_mvp_personas()

    assert first.created == 4
    assert first.updated == 0
    assert first.unchanged == 0
    assert second.created == 0
    assert second.updated == 0
    assert second.unchanged == 4

    async with payment_db() as session:
        personas = list(await session.scalars(select(Persona).order_by(Persona.code)))
    assert [persona.code for persona in personas] == [
        "astrologer",
        "love_oracle",
        "mystical_psychologist",
        "tarot_reader",
    ]
    assert all(persona.enabled for persona in personas)


async def test_sync_repairs_managed_records_and_preserves_unknown_personas(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    service = PersonaRegistryService(payment_db)
    await service.sync_mvp_personas()

    async with payment_db.begin() as session:
        tarot = await session.scalar(select(Persona).where(Persona.code == "tarot_reader"))
        assert tarot is not None
        tarot.display_name = "Old name"
        tarot.prompt_version = "old-prompt"
        tarot.enabled = False
        session.add(
            Persona(
                code="experimental_oracle",
                display_name="Experimental",
                prompt_version="experimental-v1",
                schema_version="experimental-result-v1",
                enabled=False,
            )
        )

    result = await service.sync_mvp_personas()

    assert result.created == 0
    assert result.updated == 1
    assert result.unchanged == 3

    async with payment_db() as session:
        tarot = await session.scalar(select(Persona).where(Persona.code == "tarot_reader"))
        experimental = await session.scalar(
            select(Persona).where(Persona.code == "experimental_oracle")
        )
        count = await session.scalar(select(func.count()).select_from(Persona))
    assert tarot is not None
    assert tarot.display_name == "Таролог"
    assert tarot.prompt_version == "tarot-reader-v2"
    assert tarot.enabled is True
    assert experimental is not None
    assert experimental.enabled is False
    assert count == 5
