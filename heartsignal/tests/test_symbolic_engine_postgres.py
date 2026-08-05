"""PostgreSQL integration for deterministic symbols persisted on Reading replay."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.reading_models import ReadingSymbol
from app.domain.reading import ReadingDraftRequest
from app.services.persona_registry import PersonaRegistryService
from app.services.reading_service import ReadingService
from app.services.sensitive_content import AESGCMSensitiveContentCipher
from app.services.symbolic_engine import TarotSymbolicEngine

pytestmark = pytest.mark.postgres


async def test_worker_replay_persists_the_same_tarot_symbols(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    await PersonaRegistryService(payment_db).sync_mvp_personas()
    async with payment_db.begin() as session:
        user = User(telegram_user_id=881001, first_name="Tarot")
        session.add(user)
        await session.flush()
        user_id = user.id

    reading_service = ReadingService(
        payment_db,
        AESGCMSensitiveContentCipher("tarot-replay-postgres-key-material"),
    )
    reading = await reading_service.create_draft(
        user_id,
        ReadingDraftRequest(
            persona_code="tarot_reader",
            topic="decision",
            question="Which factor deserves my attention?",
            engine_version="symbolic-v1",
            prompt_version="tarot-reader-v1",
            schema_version="reading-result-v1",
        ),
    )
    engine = TarotSymbolicEngine()
    first_draw = engine.draw(reading.id, "three_card_v1")

    await reading_service.start_generation(reading.id, user_id)
    await reading_service.complete_preview(
        reading.id,
        user_id,
        {"title": "Preview"},
        [item.to_reading_symbol() for item in first_draw],
    )

    replay_draw = engine.draw(reading.id, "three_card_v1")
    assert replay_draw == first_draw
    await reading_service.start_generation(reading.id, user_id)
    await reading_service.complete_preview(
        reading.id,
        user_id,
        {"title": "Replay preview"},
        [item.to_reading_symbol() for item in replay_draw],
    )

    async with payment_db() as session:
        stored = list(
            await session.scalars(
                select(ReadingSymbol)
                .where(ReadingSymbol.reading_id == reading.id)
                .order_by(ReadingSymbol.ordinal)
            )
        )
    assert [symbol.symbol_id for symbol in stored] == [item.card.code for item in first_draw]
    assert [symbol.position for symbol in stored] == [item.position for item in first_draw]
    assert [symbol.orientation for symbol in stored] == [
        item.orientation.value for item in first_draw
    ]
