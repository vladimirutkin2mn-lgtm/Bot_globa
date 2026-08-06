"""Transactional exact deduplication and quality metrics for oracle memory."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.memory_models import (
    OracleMemoryConsent,
    OracleMemoryItem,
    OracleMemoryPrivateContent,
)
from app.domain.memory_quality import MemoryQualitySummary
from app.domain.oracle_memory import (
    CURRENT_MEMORY_CONSENT_VERSION,
    MemoryClaimBasis,
    MemoryCreateRequest,
    MemoryItemStatus,
    MemoryKind,
    MemorySourceType,
)
from app.services.oracle_memory import (
    MemoryConsentRequiredError,
    MemoryProvenanceError,
    OracleMemoryService,
)
from app.services.oracle_memory_quality import (
    memory_content_fingerprint,
    memory_is_stale,
)
from app.services.sensitive_content import (
    ContentPurpose,
    FingerprintingSensitiveContentCipher,
)


class QualityManagedOracleMemoryService(OracleMemoryService):
    """Preserve base consent semantics while reconciling exact active duplicates."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: FingerprintingSensitiveContentCipher,
        *,
        consent_version: str = CURRENT_MEMORY_CONSENT_VERSION,
    ) -> None:
        super().__init__(sessions, cipher, consent_version=consent_version)
        self._quality_cipher = cipher

    async def remember(self, user_id: UUID, request: MemoryCreateRequest) -> OracleMemoryItem:
        async with self._sessions.begin() as session:
            await self._required_active_user(session, user_id, for_update=True)
            consent = await session.get(OracleMemoryConsent, user_id, with_for_update=True)
            if not self._permits_memory(consent):
                raise MemoryConsentRequiredError("explicit oracle memory consent is required")

            source_persona_code = request.source_persona_code
            if request.source_type is MemorySourceType.READING_DERIVED:
                source_persona_code = await self._validate_reading_provenance(
                    session,
                    user_id,
                    request.source_reading_id,
                    request.source_persona_code,
                )
                existing_candidate = await self._existing_extracted_item(session, user_id, request)
                if existing_candidate is not None:
                    return existing_candidate

            fingerprints, _ = await self._active_fingerprint_index(
                session,
                user_id,
                reconcile=True,
            )
            fingerprint = memory_content_fingerprint(
                self._quality_cipher,
                request.kind,
                request.value,
            )
            duplicate = fingerprints.get(fingerprint)
            if duplicate is not None:
                if self._should_supersede(duplicate, request):
                    await self._purge_items(session, [duplicate], datetime.now(UTC))
                else:
                    return duplicate

            item = await self._create_item(
                session,
                user_id,
                request,
                source_persona_code=source_persona_code,
            )
            await session.flush()
            return item

    async def remember_extracted_reading(
        self,
        user_id: UUID,
        reading_id: UUID,
        requests: Sequence[MemoryCreateRequest],
    ) -> tuple[list[OracleMemoryItem], int]:
        if not requests:
            return [], 0
        for request in requests:
            if (
                request.source_type is not MemorySourceType.READING_DERIVED
                or request.source_reading_id != reading_id
                or request.candidate_key is None
            ):
                raise MemoryProvenanceError("invalid completed-reading extraction request")

        unique_candidates: dict[tuple[str, str], MemoryCreateRequest] = {}
        for request in requests:
            assert request.candidate_key is not None
            key = (request.extraction_version, request.candidate_key)
            previous = unique_candidates.get(key)
            if previous is not None and previous != request:
                raise MemoryProvenanceError("conflicting extraction candidate key")
            unique_candidates[key] = request

        async with self._sessions.begin() as session:
            await self._required_active_user(session, user_id, for_update=True)
            consent = await session.get(OracleMemoryConsent, user_id, with_for_update=True)
            if not self._permits_memory(consent):
                raise MemoryConsentRequiredError("explicit oracle memory consent is required")

            persona_code = await self._validate_reading_provenance(
                session,
                user_id,
                reading_id,
                None,
            )
            for request in unique_candidates.values():
                if (
                    request.source_persona_code is not None
                    and request.source_persona_code != persona_code
                ):
                    raise MemoryProvenanceError("source persona does not match reading provenance")

            versions = {request.extraction_version for request in unique_candidates.values()}
            candidate_keys = {
                request.candidate_key
                for request in unique_candidates.values()
                if request.candidate_key is not None
            }
            existing_candidates = {
                (item.extraction_version, item.candidate_key)
                for item in (
                    await session.scalars(
                        select(OracleMemoryItem)
                        .where(
                            OracleMemoryItem.user_id == user_id,
                            OracleMemoryItem.source_reading_id == reading_id,
                            OracleMemoryItem.source_type == MemorySourceType.READING_DERIVED.value,
                            OracleMemoryItem.status == MemoryItemStatus.ACTIVE.value,
                            OracleMemoryItem.extraction_version.in_(versions),
                            OracleMemoryItem.candidate_key.in_(candidate_keys),
                        )
                        .with_for_update()
                    )
                ).all()
                if item.candidate_key is not None
            }
            fingerprints, _ = await self._active_fingerprint_index(
                session,
                user_id,
                reconcile=True,
            )

            created: list[OracleMemoryItem] = []
            skipped = len(requests) - len(unique_candidates)
            for candidate_key, request in unique_candidates.items():
                if candidate_key in existing_candidates:
                    skipped += 1
                    continue
                fingerprint = memory_content_fingerprint(
                    self._quality_cipher,
                    request.kind,
                    request.value,
                )
                duplicate = fingerprints.get(fingerprint)
                if duplicate is not None:
                    if self._should_supersede(duplicate, request):
                        await self._purge_items(session, [duplicate], datetime.now(UTC))
                    else:
                        skipped += 1
                        continue
                item = await self._create_item(
                    session,
                    user_id,
                    request,
                    source_persona_code=persona_code,
                )
                created.append(item)
                fingerprints[fingerprint] = item
            await session.flush()
            return created, skipped

    async def correct_item(
        self,
        user_id: UUID,
        memory_item_id: UUID,
        value: str,
    ) -> UUID | None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._required_active_user(session, user_id, for_update=True)
            consent = await session.get(OracleMemoryConsent, user_id, with_for_update=True)
            if not self._permits_memory(consent):
                raise MemoryConsentRequiredError("explicit oracle memory consent is required")
            item = cast(
                OracleMemoryItem | None,
                await session.scalar(
                    select(OracleMemoryItem)
                    .where(
                        OracleMemoryItem.id == memory_item_id,
                        OracleMemoryItem.user_id == user_id,
                        OracleMemoryItem.status == MemoryItemStatus.ACTIVE.value,
                    )
                    .with_for_update()
                ),
            )
            if item is None:
                return None

            request = MemoryCreateRequest(
                kind=MemoryKind(item.kind),
                value=value,
                confidence_milli=1000,
                claim_basis=MemoryClaimBasis.USER_STATED,
                source_type=MemorySourceType.USER_EXPLICIT,
                extraction_version="user-correction-v1",
            )
            fingerprints, _ = await self._active_fingerprint_index(
                session,
                user_id,
                reconcile=True,
                excluded_ids={item.id},
            )
            fingerprint = memory_content_fingerprint(
                self._quality_cipher,
                request.kind,
                request.value,
            )
            duplicate = fingerprints.get(fingerprint)
            await self._purge_items(session, [item], now)
            if (
                duplicate is not None
                and duplicate.claim_basis == MemoryClaimBasis.USER_STATED.value
            ):
                await session.flush()
                return duplicate.id
            if duplicate is not None:
                await self._purge_items(session, [duplicate], now)

            replacement = await self._create_item(
                session,
                user_id,
                request,
                source_persona_code=None,
            )
            await session.flush()
            return replacement.id

    async def reconcile_exact_duplicates(self, user_id: UUID) -> int:
        async with self._sessions.begin() as session:
            await self._required_active_user(session, user_id, for_update=True)
            consent = await session.get(OracleMemoryConsent, user_id, with_for_update=True)
            if not self._permits_memory(consent):
                raise MemoryConsentRequiredError("explicit oracle memory consent is required")
            _, retired = await self._active_fingerprint_index(
                session,
                user_id,
                reconcile=True,
            )
            await session.flush()
            return retired

    async def quality_summary(self, user_id: UUID) -> MemoryQualitySummary:
        observed_at = datetime.now(UTC)
        active = await self.list_active(user_id)
        fingerprint_counts: dict[str, int] = {}
        for item in active:
            fingerprint = memory_content_fingerprint(
                self._quality_cipher,
                item.kind,
                item.value,
            )
            fingerprint_counts[fingerprint] = fingerprint_counts.get(fingerprint, 0) + 1
        return MemoryQualitySummary(
            active_count=len(active),
            user_stated_count=sum(
                item.claim_basis is MemoryClaimBasis.USER_STATED for item in active
            ),
            model_inferred_count=sum(
                item.claim_basis is MemoryClaimBasis.MODEL_INFERRED for item in active
            ),
            stale_count=sum(
                memory_is_stale(item.kind, item.created_at, now=observed_at) for item in active
            ),
            correction_count=sum(
                item.extraction_version == "user-correction-v1" for item in active
            ),
            duplicate_group_count=sum(count > 1 for count in fingerprint_counts.values()),
            observed_at=observed_at,
        )

    async def _active_fingerprint_index(
        self,
        session: AsyncSession,
        user_id: UUID,
        *,
        reconcile: bool,
        excluded_ids: set[UUID] | None = None,
    ) -> tuple[dict[str, OracleMemoryItem], int]:
        excluded = excluded_ids or set()
        rows = list(
            (
                await session.execute(
                    select(OracleMemoryItem, OracleMemoryPrivateContent)
                    .join(
                        OracleMemoryPrivateContent,
                        OracleMemoryPrivateContent.memory_item_id == OracleMemoryItem.id,
                    )
                    .where(
                        OracleMemoryItem.user_id == user_id,
                        OracleMemoryItem.status == MemoryItemStatus.ACTIVE.value,
                        OracleMemoryPrivateContent.value_ciphertext.is_not(None),
                    )
                    .order_by(OracleMemoryItem.id)
                    .with_for_update()
                )
            ).all()
        )
        fingerprints: dict[str, OracleMemoryItem] = {}
        losers: list[OracleMemoryItem] = []
        for item, private in rows:
            if item.id in excluded:
                continue
            assert private.value_ciphertext is not None
            value = self._cipher.decrypt_json(
                ContentPurpose.ORACLE_MEMORY_VALUE,
                private.value_ciphertext,
            )
            if not isinstance(value, str):
                raise ValueError("invalid decrypted oracle memory shape")
            fingerprint = memory_content_fingerprint(
                self._quality_cipher,
                MemoryKind(item.kind),
                value,
            )
            current = fingerprints.get(fingerprint)
            if current is None:
                fingerprints[fingerprint] = item
                continue
            if self._preference_key(item) > self._preference_key(current):
                losers.append(current)
                fingerprints[fingerprint] = item
            else:
                losers.append(item)
        if reconcile and losers:
            await self._purge_items(session, losers, datetime.now(UTC))
        return fingerprints, len(losers)

    @staticmethod
    def _preference_key(item: OracleMemoryItem) -> tuple[int, int, datetime, str]:
        return (
            int(item.claim_basis == MemoryClaimBasis.USER_STATED.value),
            item.confidence_milli,
            item.created_at,
            str(item.id),
        )

    @staticmethod
    def _should_supersede(
        existing: OracleMemoryItem,
        request: MemoryCreateRequest,
    ) -> bool:
        return (
            existing.claim_basis == MemoryClaimBasis.MODEL_INFERRED.value
            and request.claim_basis is MemoryClaimBasis.USER_STATED
        )
