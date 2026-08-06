"""PostgreSQL invariants for oracle memory retention and content-free telemetry."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.memory_models import (
    OracleMemoryEvent,
    OracleMemoryItem,
    OracleMemoryPrivateContent,
)
from app.db.models import User
from app.domain.memory_lifecycle import MemoryLifecycleEventType
from app.domain.oracle_memory import (
    MemoryClaimBasis,
    MemoryCreateRequest,
    MemoryItemStatus,
    MemoryKind,
    MemorySourceType,
)
from app.services.oracle_memory_quality_service import (
    MemoryCapacityError,
    QualityManagedOracleMemoryService,
)
from app.services.reading_memory_context import OracleReadingMemoryRetriever
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres


async def _user(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> User:
    async with sessions.begin() as session:
        user = User(telegram_user_id=telegram_id, first_name="Memory Lifecycle")
        session.add(user)
        await session.flush()
        return user


def _request(
    value: str,
    *,
    kind: MemoryKind = MemoryKind.USER_STATEMENT,
    basis: MemoryClaimBasis = MemoryClaimBasis.USER_STATED,
    confidence: int = 900,
    version: str = "lifecycle-test-v1",
) -> MemoryCreateRequest:
    return MemoryCreateRequest(
        kind=kind,
        value=value,
        confidence_milli=confidence,
        claim_basis=basis,
        source_type=MemorySourceType.PROFILE_IMPORTED,
        extraction_version=version,
    )


async def test_prompt_selection_records_use_without_exposing_value(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 990001)
    marker = "private-bankruptcy-memory-marker"
    cipher = AESGCMSensitiveContentCipher("ora-307-usage-ledger-key")
    service = QualityManagedOracleMemoryService(payment_db, cipher)
    await service.grant_consent(user.id)
    item = await service.remember(
        user.id,
        _request(f"My lawyer discussed bankruptcy {marker}"),
    )

    retriever = OracleReadingMemoryRetriever(service)
    selected = await retriever.retrieve(
        user.id,
        persona_code="tarot_reader",
        topic="decision",
        question="How should I reflect on bankruptcy?",
        context="This involved a lawyer",
    )

    assert [entry.value for entry in selected] == [f"My lawyer discussed bankruptcy {marker}"]
    async with payment_db() as session:
        stored = await session.get(OracleMemoryItem, item.id)
        events = list(
            await session.scalars(
                select(OracleMemoryEvent).where(OracleMemoryEvent.user_id == user.id)
            )
        )
    assert stored is not None and stored.use_count == 1
    assert stored.last_used_at is not None
    used = [event for event in events if event.event_type == MemoryLifecycleEventType.USED.value]
    assert len(used) == 1 and used[0].memory_item_id == item.id
    assert marker not in repr(events)


async def test_retention_decays_only_stale_low_confidence_model_inference(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 990002)
    cipher = AESGCMSensitiveContentCipher("ora-307-decay-key")
    service = QualityManagedOracleMemoryService(payment_db, cipher, decay_confidence_milli=650)
    await service.grant_consent(user.id)
    inferred = await service.remember(
        user.id,
        _request(
            "The user may avoid one relationship conversation",
            kind=MemoryKind.RELATIONSHIP_NOTES,
            basis=MemoryClaimBasis.MODEL_INFERRED,
            confidence=600,
        ),
    )
    stated = await service.remember(
        user.id,
        _request(
            "I avoid one relationship conversation",
            kind=MemoryKind.RELATIONSHIP_NOTES,
            basis=MemoryClaimBasis.USER_STATED,
            confidence=500,
        ),
    )
    old = datetime.now(UTC) - timedelta(days=181)
    async with payment_db.begin() as session:
        for item_id in (inferred.id, stated.id):
            row = await session.get(OracleMemoryItem, item_id, with_for_update=True)
            assert row is not None
            row.created_at = old

    assert await service.reconcile_retention(user.id) == 1
    active = await service.list_active(user.id)
    assert [item.id for item in active] == [stated.id]
    async with payment_db() as session:
        retired = await session.get(OracleMemoryItem, inferred.id)
        private = await session.get(OracleMemoryPrivateContent, inferred.id)
        events = list(
            await session.scalars(
                select(OracleMemoryEvent).where(
                    OracleMemoryEvent.user_id == user.id,
                    OracleMemoryEvent.event_type == MemoryLifecycleEventType.DECAYED.value,
                )
            )
        )
    assert retired is not None and retired.status == MemoryItemStatus.DELETED.value
    assert private is not None and private.value_ciphertext is None
    assert len(events) == 1 and events[0].memory_item_id == inferred.id


async def test_capacity_retires_only_model_inferred_memory(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 990003)
    cipher = AESGCMSensitiveContentCipher("ora-307-capacity-key")
    service = QualityManagedOracleMemoryService(
        payment_db,
        cipher,
        max_active_items=3,
        max_model_inferred_items=1,
    )
    await service.grant_consent(user.id)
    first = await service.remember(user.id, _request("I value stability"))
    second = await service.remember(user.id, _request("I value autonomy"))
    inferred = await service.remember(
        user.id,
        _request(
            "The user may prefer a leadership role",
            kind=MemoryKind.PERSONAL_GOAL,
            basis=MemoryClaimBasis.MODEL_INFERRED,
            confidence=800,
        ),
    )
    third = await service.remember(user.id, _request("I value learning"))

    active_ids = {item.id for item in await service.list_active(user.id)}
    assert active_ids == {first.id, second.id, third.id}
    assert inferred.id not in active_ids
    async with payment_db() as session:
        retired = await session.get(OracleMemoryItem, inferred.id)
        private = await session.get(OracleMemoryPrivateContent, inferred.id)
        event = await session.scalar(
            select(OracleMemoryEvent).where(
                OracleMemoryEvent.memory_item_id == inferred.id,
                OracleMemoryEvent.event_type
                == MemoryLifecycleEventType.CAPACITY_RETIRED.value,
            )
        )
    assert retired is not None and retired.status == MemoryItemStatus.DELETED.value
    assert private is not None and private.value_ciphertext is None
    assert event is not None


async def test_full_user_stated_memory_rejects_write_without_deleting_existing_items(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 990004)
    cipher = AESGCMSensitiveContentCipher("ora-307-user-capacity-key")
    service = QualityManagedOracleMemoryService(
        payment_db,
        cipher,
        max_active_items=2,
        max_model_inferred_items=1,
    )
    await service.grant_consent(user.id)
    first = await service.remember(user.id, _request("I prefer direct answers"))
    second = await service.remember(user.id, _request("I prefer short readings"))

    with pytest.raises(MemoryCapacityError):
        await service.remember(user.id, _request("I prefer practical next steps"))

    assert {item.id for item in await service.list_active(user.id)} == {first.id, second.id}


async def test_correction_persists_supersession_and_usefulness_counts(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 990005)
    cipher = AESGCMSensitiveContentCipher("ora-307-supersession-key")
    service = QualityManagedOracleMemoryService(payment_db, cipher)
    await service.grant_consent(user.id)
    original = await service.remember(user.id, _request("I want to change roles"))
    replacement_id = await service.correct_item(
        user.id,
        original.id,
        "I want to move into a leadership role",
    )
    assert replacement_id is not None

    async with payment_db() as session:
        replacement = await session.get(OracleMemoryItem, replacement_id)
        original_private = await session.get(OracleMemoryPrivateContent, original.id)
    assert replacement is not None and replacement.supersedes_item_id == original.id
    assert original_private is not None and original_private.value_ciphertext is None

    summary = await service.usefulness_summary(user.id)
    assert summary.created_count == 2
    assert summary.corrected_count == 1
    assert summary.used_count == 0
