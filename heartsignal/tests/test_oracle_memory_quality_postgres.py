"""PostgreSQL invariants for exact memory deduplication and quality metrics."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
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
from app.services.oracle_memory_quality_service import QualityManagedOracleMemoryService
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres


async def _user(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> User:
    async with sessions.begin() as session:
        user = User(telegram_user_id=telegram_id, first_name="Memory Quality")
        session.add(user)
        await session.flush()
        return user


def _request(
    value: str,
    *,
    kind: MemoryKind = MemoryKind.USER_STATEMENT,
    basis: MemoryClaimBasis = MemoryClaimBasis.USER_STATED,
    source: MemorySourceType = MemorySourceType.USER_EXPLICIT,
    version: str = "quality-test-v1",
) -> MemoryCreateRequest:
    return MemoryCreateRequest(
        kind=kind,
        value=value,
        confidence_milli=900,
        claim_basis=basis,
        source_type=source,
        extraction_version=version,
    )


async def test_concurrent_exact_writes_return_one_active_item(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 980000)
    cipher = AESGCMSensitiveContentCipher("ora-306-concurrent-dedup-key")
    service = QualityManagedOracleMemoryService(payment_db, cipher)
    await service.grant_consent(user.id)

    first, second = await asyncio.gather(
        service.remember(
            user.id,
            _request("My lawyer discussed bankruptcy during financial stress"),
        ),
        service.remember(
            user.id,
            _request("  MY lawyer discussed bankruptcy during financial stress  "),
        ),
    )

    assert first.id == second.id
    active = await service.list_active(user.id)
    assert [item.id for item in active] == [first.id]


async def test_quality_service_reconciles_legacy_duplicates_and_purges_loser_ciphertext(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 980001)
    cipher = AESGCMSensitiveContentCipher("ora-306-legacy-dedup-key")
    legacy = OracleMemoryService(payment_db, cipher)
    await legacy.grant_consent(user.id)
    first = await legacy.remember(
        user.id,
        _request("Financial stress after bankruptcy", kind=MemoryKind.USER_STATEMENT),
    )
    second = await legacy.remember(
        user.id,
        _request("  FINANCIAL   stress after bankruptcy  ", kind=MemoryKind.USER_STATEMENT),
    )
    assert first.id != second.id

    quality = QualityManagedOracleMemoryService(payment_db, cipher)
    assert await quality.reconcile_exact_duplicates(user.id) == 1
    active = await quality.list_active(user.id)
    assert len(active) == 1
    assert active[0].id in {first.id, second.id}

    async with payment_db() as session:
        rows = [
            (
                await session.get(OracleMemoryItem, item_id),
                await session.get(OracleMemoryPrivateContent, item_id),
            )
            for item_id in (first.id, second.id)
        ]
    deleted = [
        (item, private) for item, private in rows if item is not None and item.status == "deleted"
    ]
    assert len(deleted) == 1
    deleted_item, deleted_private = deleted[0]
    assert deleted_item is not None and deleted_item.deleted_at is not None
    assert deleted_private is not None and deleted_private.value_ciphertext is None
    assert deleted_private.content_deleted_at is not None
    summary = await quality.quality_summary(user.id)
    assert summary.active_count == 1
    assert summary.duplicate_group_count == 0


async def test_user_stated_exact_value_supersedes_equal_model_inference(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 980002)
    cipher = AESGCMSensitiveContentCipher("ora-306-supersession-key")
    service = QualityManagedOracleMemoryService(payment_db, cipher)
    await service.grant_consent(user.id)
    inferred = await service.remember(
        user.id,
        _request(
            "The user may be considering a career change",
            kind=MemoryKind.PERSONAL_GOAL,
            basis=MemoryClaimBasis.MODEL_INFERRED,
            source=MemorySourceType.PROFILE_IMPORTED,
        ),
    )
    explicit = await service.remember(
        user.id,
        _request(
            "  THE USER may be considering a career change  ",
            kind=MemoryKind.PERSONAL_GOAL,
            basis=MemoryClaimBasis.USER_STATED,
        ),
    )

    assert explicit.id != inferred.id
    active = await service.list_active(user.id)
    assert len(active) == 1
    assert active[0].id == explicit.id
    assert active[0].claim_basis is MemoryClaimBasis.USER_STATED

    async with payment_db() as session:
        old_item = await session.get(OracleMemoryItem, inferred.id)
        old_private = await session.get(OracleMemoryPrivateContent, inferred.id)
    assert old_item is not None and old_item.status == MemoryItemStatus.DELETED.value
    assert old_private is not None and old_private.value_ciphertext is None


async def test_quality_summary_counts_stale_and_corrected_items_without_values(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 980003)
    cipher = AESGCMSensitiveContentCipher("ora-306-summary-key")
    service = QualityManagedOracleMemoryService(payment_db, cipher)
    await service.grant_consent(user.id)
    goal = await service.remember(
        user.id,
        _request("I want to change roles", kind=MemoryKind.PERSONAL_GOAL),
    )
    replacement_id = await service.correct_item(
        user.id,
        goal.id,
        "I want to move into a leadership role",
    )
    assert replacement_id is not None
    relationship = await service.remember(
        user.id,
        _request(
            "I keep avoiding one difficult relationship conversation",
            kind=MemoryKind.RELATIONSHIP_NOTES,
        ),
    )
    async with payment_db.begin() as session:
        row = await session.get(OracleMemoryItem, relationship.id, with_for_update=True)
        assert row is not None
        row.created_at = datetime.now(UTC) - timedelta(days=181)

    summary = await service.quality_summary(user.id)
    assert summary.active_count == 2
    assert summary.user_stated_count == 2
    assert summary.model_inferred_count == 0
    assert summary.stale_count == 1
    assert summary.correction_count == 1
    assert summary.duplicate_group_count == 0
