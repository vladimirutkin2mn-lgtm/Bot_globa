"""PostgreSQL consent and ownership boundaries for reading memory retrieval."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import pytest

from app.db.models import User
from app.domain.oracle_memory import (
    MemoryClaimBasis,
    MemoryCreateRequest,
    MemoryKind,
    MemorySourceType,
)
from app.services.oracle_memory import OracleMemoryService
from app.services.reading_memory_context import OracleReadingMemoryRetriever
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres


async def test_retrieval_requires_consent_and_never_crosses_user_boundary(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    async with payment_db.begin() as session:
        owner = User(telegram_user_id=970001, first_name="Owner")
        stranger = User(telegram_user_id=970002, first_name="Stranger")
        session.add_all((owner, stranger))
        await session.flush()
        owner_id, stranger_id = owner.id, stranger.id

    cipher = AESGCMSensitiveContentCipher("ora-305-retrieval-key")
    memory = OracleMemoryService(payment_db, cipher)
    retriever = OracleReadingMemoryRetriever(memory)
    await memory.grant_consent(owner_id)
    await memory.remember(
        owner_id,
        MemoryCreateRequest(
            kind=MemoryKind.USER_STATEMENT,
            value="My lawyer discussed bankruptcy while I was under financial stress",
            confidence_milli=950,
            claim_basis=MemoryClaimBasis.USER_STATED,
            source_type=MemorySourceType.USER_EXPLICIT,
            extraction_version="manual-v1",
        ),
    )

    owner_context = await retriever.retrieve(
        owner_id,
        persona_code="tarot_reader",
        topic="decision",
        question="How should I reflect on bankruptcy and financial stress?",
        context="This involved a lawyer",
    )
    assert [item.value for item in owner_context] == [
        "My lawyer discussed bankruptcy while I was under financial stress"
    ]

    stranger_context = await retriever.retrieve(
        stranger_id,
        persona_code="tarot_reader",
        topic="decision",
        question="How should I reflect on bankruptcy and financial stress?",
        context="This involved a lawyer",
    )
    assert stranger_context == ()

    await memory.revoke_consent(owner_id)
    assert (
        await retriever.retrieve(
            owner_id,
            persona_code="tarot_reader",
            topic="decision",
            question="How should I reflect on bankruptcy and financial stress?",
            context="This involved a lawyer",
        )
        == ()
    )
