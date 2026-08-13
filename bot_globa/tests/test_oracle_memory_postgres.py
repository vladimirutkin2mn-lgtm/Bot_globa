"""PostgreSQL invariants for explicit-consent encrypted oracle memory."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.memory_models import (
    OracleMemoryConsent,
    OracleMemoryItem,
    OracleMemoryPrivateContent,
)
from app.db.models import CreditTransaction, User
from app.db.reading_models import Persona, Reading
from app.domain.oracle_memory import (
    MemoryClaimBasis,
    MemoryConsentStatus,
    MemoryCreateRequest,
    MemoryItemStatus,
    MemoryKind,
    MemorySourceType,
)
from app.providers.analytics import NoOpAnalyticsClient
from app.services.data_deletion import DataDeletionOutcome, DataDeletionService
from app.services.oracle_memory import (
    MemoryConsentRequiredError,
    MemoryProvenanceError,
    OracleMemoryService,
)
from app.services.sensitive_content import AESGCMSensitiveContentCipher

pytestmark = pytest.mark.postgres


def _explicit(value: str, *, kind: MemoryKind = MemoryKind.PERSONAL_GOAL) -> MemoryCreateRequest:
    return MemoryCreateRequest(
        kind=kind,
        value=value,
        confidence_milli=900,
        source_type=MemorySourceType.USER_EXPLICIT,
        extraction_version="manual-v1",
    )


async def _user(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> User:
    async with sessions.begin() as session:
        user = User(telegram_user_id=telegram_id, first_name="Memory")
        session.add(user)
        await session.flush()
        return user


async def test_memory_requires_explicit_consent_and_encrypts_value_at_rest(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 930001)
    secret = "I prefer to be heard before receiving a solution"
    service = OracleMemoryService(
        payment_db,
        AESGCMSensitiveContentCipher("oracle-memory-postgres-key"),
    )

    with pytest.raises(MemoryConsentRequiredError) as blocked:
        await service.remember(user.id, _explicit(secret))
    assert secret not in str(blocked.value)

    consent = await service.grant_consent(user.id)
    assert consent.status is MemoryConsentStatus.GRANTED
    assert consent.permits_memory

    item = await service.remember(user.id, _explicit(secret))
    assert item.status == MemoryItemStatus.ACTIVE.value
    async with payment_db() as session:
        private = await session.get(OracleMemoryPrivateContent, item.id)
        assert private is not None and private.value_ciphertext is not None
        assert secret.encode() not in private.value_ciphertext
        assert not hasattr(item, "value")

    active = await service.list_active(user.id)
    assert len(active) == 1
    assert active[0].value == secret
    assert active[0].kind is MemoryKind.PERSONAL_GOAL
    assert active[0].claim_basis is MemoryClaimBasis.USER_STATED


async def test_memory_consent_is_off_by_default_and_offered_after_second_full_reading(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 930010)
    service = OracleMemoryService(
        payment_db,
        AESGCMSensitiveContentCipher("oracle-memory-contextual-offer-key"),
    )
    async with payment_db.begin() as session:
        persona = Persona(
            code="contextual_offer",
            display_name="Contextual Offer",
            prompt_version="offer-v1",
            schema_version="reading-result-v1",
        )
        session.add(persona)
        await session.flush()

    assert not await service.should_offer_consent(user.id)
    for expected in (False, True):
        async with payment_db.begin() as session:
            reading = Reading(
                user_id=user.id,
                persona_id=persona.id,
                topic="decision",
                status="draft",
                access_level="none",
                cost_units=0,
                engine_version="reading-v1",
                prompt_version="offer-v1",
                schema_version="reading-result-v1",
            )
            session.add(reading)
            await session.flush()
            spend = CreditTransaction(
                user_id=user.id,
                type="spend",
                amount=-1,
                idempotency_key=f"contextual-offer:{reading.id}",
                reading_id=reading.id,
            )
            session.add(spend)
            await session.flush()
            reading.status = "full_ready"
            reading.access_level = "full"
            reading.cost_units = 1
            reading.full_access_transaction_id = spend.id
            reading.generated_at = datetime.now(UTC)
        assert await service.should_offer_consent(user.id) is expected

    await service.revoke_consent(user.id)
    assert not await service.should_offer_consent(user.id)


async def test_revoking_consent_purges_all_values_and_blocks_new_memory(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 930002)
    service = OracleMemoryService(
        payment_db,
        AESGCMSensitiveContentCipher("oracle-memory-revoke-key"),
    )
    await service.grant_consent(user.id)
    await service.remember(user.id, _explicit("I prefer concise answers"))
    await service.remember(
        user.id,
        _explicit("I want to express boundaries clearly", kind=MemoryKind.PERSONAL_GOAL),
    )

    revoked = await service.revoke_consent(user.id)
    assert revoked.status is MemoryConsentStatus.REVOKED
    assert revoked.revoked_at is not None
    assert await service.list_active(user.id) == []

    async with payment_db() as session:
        items = list(
            await session.scalars(
                select(OracleMemoryItem)
                .where(OracleMemoryItem.user_id == user.id)
                .order_by(OracleMemoryItem.id)
            )
        )
        private_rows = list(
            await session.scalars(
                select(OracleMemoryPrivateContent).order_by(
                    OracleMemoryPrivateContent.memory_item_id
                )
            )
        )
        assert items and all(item.status == MemoryItemStatus.DELETED.value for item in items)
        assert all(item.deleted_at is not None for item in items)
        assert private_rows and all(row.value_ciphertext is None for row in private_rows)
        assert all(row.value_format_version is None for row in private_rows)
        assert all(row.content_deleted_at is not None for row in private_rows)

    repeated = await service.revoke_consent(user.id)
    assert repeated.revoked_at == revoked.revoked_at
    with pytest.raises(MemoryConsentRequiredError):
        await service.remember(user.id, _explicit("This must not be stored"))


async def test_reading_derived_memory_requires_owned_completed_matching_provenance(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    async with payment_db.begin() as session:
        owner = User(telegram_user_id=930003, first_name="Owner")
        stranger = User(telegram_user_id=930004, first_name="Stranger")
        persona = Persona(
            code="tarot_reader",
            display_name="Tarot Reader",
            prompt_version="tarot-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((owner, stranger, persona))
        await session.flush()
        owned = Reading(
            user_id=owner.id,
            persona_id=persona.id,
            topic="decision",
            status="draft",
            access_level="none",
            cost_units=0,
            engine_version="reading-v1",
            prompt_version="tarot-v1",
            schema_version="reading-result-v1",
        )
        foreign = Reading(
            user_id=stranger.id,
            persona_id=persona.id,
            topic="decision",
            status="draft",
            access_level="none",
            cost_units=0,
            engine_version="reading-v1",
            prompt_version="tarot-v1",
            schema_version="reading-result-v1",
        )
        session.add_all((owned, foreign))
        await session.flush()

    service = OracleMemoryService(
        payment_db,
        AESGCMSensitiveContentCipher("oracle-memory-provenance-key"),
    )
    await service.grant_consent(owner.id)

    def derived(reading_id: UUID, persona_code: str | None = None) -> MemoryCreateRequest:
        return MemoryCreateRequest(
            kind=MemoryKind.RECURRING_THEME,
            value="Choosing between predictability and change",
            confidence_milli=700,
            claim_basis=MemoryClaimBasis.MODEL_INFERRED,
            source_type=MemorySourceType.READING_DERIVED,
            source_reading_id=reading_id,
            source_persona_code=persona_code,
            extraction_version="extractor-v1",
            candidate_key="candidate-1",
        )

    with pytest.raises(MemoryProvenanceError):
        await service.remember(owner.id, derived(foreign.id))
    with pytest.raises(MemoryProvenanceError):
        await service.remember(owner.id, derived(owned.id))

    async with payment_db.begin() as session:
        completed = await session.get(Reading, owned.id, with_for_update=True)
        assert completed is not None
        completed.status = "preview_ready"
        completed.access_level = "preview"
        completed.generated_at = datetime.now(UTC)

    with pytest.raises(MemoryProvenanceError):
        await service.remember(owner.id, derived(owned.id, "love_oracle"))

    item = await service.remember(owner.id, derived(owned.id))
    repeated = await service.remember(owner.id, derived(owned.id))
    assert item.id == repeated.id
    assert item.source_reading_id == owned.id
    assert item.source_persona_code == "tarot_reader"
    assert item.claim_basis == MemoryClaimBasis.MODEL_INFERRED.value


async def test_account_deletion_physically_removes_memory_and_consent(
    payment_db: async_sessionmaker[AsyncSession],
) -> None:
    user = await _user(payment_db, 930005)
    service = OracleMemoryService(
        payment_db,
        AESGCMSensitiveContentCipher("oracle-memory-account-delete-key"),
    )
    await service.grant_consent(user.id)
    await service.remember(user.id, _explicit("Delete this with the account"))

    async with payment_db() as session:
        outcome = await DataDeletionService(session, NoOpAnalyticsClient()).delete_account(user.id)
    assert outcome is DataDeletionOutcome.DELETED

    async with payment_db() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OracleMemoryConsent)
                .where(OracleMemoryConsent.user_id == user.id)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OracleMemoryItem)
                .where(OracleMemoryItem.user_id == user.id)
            )
            == 0
        )
        assert (
            await session.scalar(select(func.count()).select_from(OracleMemoryPrivateContent)) == 0
        )
        persisted_user = await session.get(User, user.id)
        assert persisted_user is not None
        assert persisted_user.privacy_status == "deleted"
        assert persisted_user.deleted_at is not None
