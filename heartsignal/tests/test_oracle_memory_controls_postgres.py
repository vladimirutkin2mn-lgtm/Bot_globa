"""PostgreSQL invariants for user-controlled oracle memory management."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.memory_models import OracleMemoryItem, OracleMemoryPrivateContent
from app.db.models import User
from app.domain.oracle_memory import (
    MemoryClaimBasis,
    MemoryCreateRequest,
    MemoryItemStatus,
    MemoryKind,
    MemorySourceType,
)
from app.services.oracle_memory import OracleMemoryService
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres


def _request(value: str, *, kind: MemoryKind = MemoryKind.USER_PREFERENCE) -> MemoryCreateRequest:
    return MemoryCreateRequest(
        kind=kind,
        value=value,
        confidence_milli=850,
        source_type=MemorySourceType.USER_EXPLICIT,
        extraction_version="manual-v1",
    )


async def _user(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> User:
    async with sessions.begin() as session:
        user = User(telegram_user_id=telegram_id, first_name="Memory Controls")
        session.add(user)
        await session.flush()
        return user


async def test_correction_replaces_item_and_purges_previous_ciphertext(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 960001)
    cipher = AESGCMSensitiveContentCipher("oracle-memory-correction-key")
    service = OracleMemoryService(payment_db, cipher)
    await service.grant_consent(user.id)
    original = await service.remember(
        user.id,
        _request("I prefer long answers", kind=MemoryKind.USER_PREFERENCE),
    )

    replacement_id = await service.correct_item(
        user.id,
        original.id,
        "I prefer concise answers with a short rationale",
    )
    assert replacement_id is not None and replacement_id != original.id

    active = await service.list_active(user.id)
    assert len(active) == 1
    replacement = active[0]
    assert replacement.id == replacement_id
    assert replacement.value == "I prefer concise answers with a short rationale"
    assert replacement.kind is MemoryKind.USER_PREFERENCE
    assert replacement.claim_basis is MemoryClaimBasis.USER_STATED
    assert replacement.source_type is MemorySourceType.USER_EXPLICIT
    assert replacement.source_reading_id is None
    assert replacement.source_reading_created_at is None
    assert replacement.extraction_version == "user-correction-v1"
    assert replacement.candidate_key is None
    assert replacement.confidence_milli == 1000

    async with payment_db() as session:
        old_item = await session.get(OracleMemoryItem, original.id)
        old_private = await session.get(OracleMemoryPrivateContent, original.id)
        new_private = await session.get(OracleMemoryPrivateContent, replacement_id)
        assert old_item is not None and old_item.status == MemoryItemStatus.DELETED.value
        assert old_item.deleted_at is not None
        assert old_private is not None and old_private.value_ciphertext is None
        assert old_private.value_format_version is None
        assert old_private.content_deleted_at is not None
        assert new_private is not None and new_private.value_ciphertext is not None
        assert b"concise answers" not in new_private.value_ciphertext


async def test_correction_never_crosses_user_boundary(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    owner = await _user(payment_db, 960002)
    stranger = await _user(payment_db, 960003)
    service = OracleMemoryService(
        payment_db,
        AESGCMSensitiveContentCipher("oracle-memory-owner-key"),
    )
    await service.grant_consent(owner.id)
    await service.grant_consent(stranger.id)
    item = await service.remember(owner.id, _request("Owner-only memory"))

    assert await service.correct_item(stranger.id, item.id, "Stolen replacement") is None
    assert [view.value for view in await service.list_active(owner.id)] == ["Owner-only memory"]
    assert await service.list_active(stranger.id) == []


async def test_clear_all_purges_values_but_keeps_consent_active(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 960004)
    service = OracleMemoryService(
        payment_db,
        AESGCMSensitiveContentCipher("oracle-memory-clear-key"),
    )
    await service.grant_consent(user.id)
    first = await service.remember(user.id, _request("First memory"))
    second = await service.remember(
        user.id,
        _request("Second memory", kind=MemoryKind.PERSONAL_GOAL),
    )

    assert await service.clear_all(user.id) == 2
    assert await service.clear_all(user.id) == 0
    consent = await service.consent_state(user.id)
    assert consent is not None and consent.permits_memory
    assert await service.list_active(user.id) == []

    async with payment_db() as session:
        private_rows = list(
            await session.scalars(
                select(OracleMemoryPrivateContent).where(
                    OracleMemoryPrivateContent.memory_item_id.in_((first.id, second.id))
                )
            )
        )
        assert len(private_rows) == 2
        assert all(row.value_ciphertext is None for row in private_rows)
        assert all(row.content_deleted_at is not None for row in private_rows)

    new_value = f"Memory after clear {uuid4()}"
    remembered = await service.remember(user.id, _request(new_value))
    assert remembered.status == MemoryItemStatus.ACTIVE.value
    assert [view.value for view in await service.list_active(user.id)] == [new_value]
