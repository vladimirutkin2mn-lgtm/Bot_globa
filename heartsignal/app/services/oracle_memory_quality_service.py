"""Transactional quality, retention and usefulness management for oracle memory."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.memory_models import (
    OracleMemoryConsent,
    OracleMemoryEvent,
    OracleMemoryItem,
    OracleMemoryPrivateContent,
)
from app.domain.memory_lifecycle import MemoryLifecycleEventType, MemoryUsefulnessSummary
from app.domain.memory_quality import MemoryQualitySummary
from app.domain.oracle_memory import (
    CURRENT_MEMORY_CONSENT_VERSION,
    MemoryClaimBasis,
    MemoryConsentStatus,
    MemoryConsentView,
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


class MemoryCapacityError(RuntimeError):
    """No model-inferred item can be retired without deleting user-stated memory."""


class QualityManagedOracleMemoryService(OracleMemoryService):
    """Preserve consent while managing exact identity, retention and lifecycle events."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: FingerprintingSensitiveContentCipher,
        *,
        consent_version: str = CURRENT_MEMORY_CONSENT_VERSION,
        max_active_items: int = 200,
        max_model_inferred_items: int = 100,
        decay_confidence_milli: int = 650,
    ) -> None:
        super().__init__(sessions, cipher, consent_version=consent_version)
        if max_active_items < 1:
            raise ValueError("max active oracle memory items must be positive")
        if not 0 <= max_model_inferred_items <= max_active_items:
            raise ValueError("model-inferred memory limit must fit the active limit")
        if not 1 <= decay_confidence_milli <= 1000:
            raise ValueError("memory decay confidence must be between 1 and 1000")
        self._quality_cipher = cipher
        self._max_active_items = max_active_items
        self._max_model_inferred_items = max_model_inferred_items
        self._decay_confidence_milli = decay_confidence_milli

    async def revoke_consent(self, user_id: UUID) -> MemoryConsentView:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._required_active_user(session, user_id, for_update=True)
            consent = await session.get(OracleMemoryConsent, user_id, with_for_update=True)
            if consent is None:
                consent = OracleMemoryConsent(
                    user_id=user_id,
                    status=MemoryConsentStatus.REVOKED.value,
                    consent_version=self._consent_version,
                    accepted_at=None,
                    revoked_at=now,
                )
                session.add(consent)
            elif consent.status != MemoryConsentStatus.REVOKED.value:
                consent.status = MemoryConsentStatus.REVOKED.value
                consent.revoked_at = now
            items = await self._active_items_locked(session, user_id)
            await self._purge_with_events(
                session,
                user_id,
                items,
                now,
                MemoryLifecycleEventType.DELETED,
                reason_code="consent_revoked",
            )
            await session.flush()
            return self._view(consent)

    async def clear_all(self, user_id: UUID) -> int:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._required_active_user(session, user_id, for_update=True)
            consent = await session.get(OracleMemoryConsent, user_id, with_for_update=True)
            if not self._permits_memory(consent):
                raise MemoryConsentRequiredError("explicit oracle memory consent is required")
            items = await self._active_items_locked(session, user_id)
            await self._purge_with_events(
                session,
                user_id,
                items,
                now,
                MemoryLifecycleEventType.DELETED,
                reason_code="clear_all",
            )
            await session.flush()
            return len(items)

    async def delete_item(self, user_id: UUID, memory_item_id: UUID) -> bool:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._required_active_user(session, user_id, for_update=True)
            item = cast(
                OracleMemoryItem | None,
                await session.scalar(
                    select(OracleMemoryItem)
                    .where(
                        OracleMemoryItem.id == memory_item_id,
                        OracleMemoryItem.user_id == user_id,
                    )
                    .with_for_update()
                ),
            )
            if item is None:
                return False
            if item.status == MemoryItemStatus.DELETED.value:
                return True
            await self._purge_with_events(
                session,
                user_id,
                [item],
                now,
                MemoryLifecycleEventType.DELETED,
                reason_code="user_deleted",
            )
            await session.flush()
            return True

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
            superseded: OracleMemoryItem | None = None
            if duplicate is not None:
                if self._should_supersede(duplicate, request):
                    superseded = duplicate
                    await self._purge_items(session, [duplicate], datetime.now(UTC))
                else:
                    return duplicate

            if not await self._ensure_capacity(session, user_id, request.claim_basis):
                raise MemoryCapacityError("oracle memory capacity is reserved for user-stated items")
            item = await self._create_item(
                session,
                user_id,
                request,
                source_persona_code=source_persona_code,
            )
            if superseded is not None:
                item.supersedes_item_id = superseded.id
            self._add_creation_events(session, user_id, item, request)
            if superseded is not None:
                self._add_event(
                    session,
                    user_id,
                    MemoryLifecycleEventType.SUPERSEDED,
                    memory_item_id=superseded.id,
                    related_memory_item_id=item.id,
                    reason_code="user_stated_exact_match",
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
                superseded: OracleMemoryItem | None = None
                if duplicate is not None:
                    if self._should_supersede(duplicate, request):
                        superseded = duplicate
                        await self._purge_items(session, [duplicate], datetime.now(UTC))
                    else:
                        skipped += 1
                        continue
                if not await self._ensure_capacity(session, user_id, request.claim_basis):
                    skipped += 1
                    continue
                item = await self._create_item(
                    session,
                    user_id,
                    request,
                    source_persona_code=persona_code,
                )
                if superseded is not None:
                    item.supersedes_item_id = superseded.id
                self._add_creation_events(session, user_id, item, request)
                if superseded is not None:
                    self._add_event(
                        session,
                        user_id,
                        MemoryLifecycleEventType.SUPERSEDED,
                        memory_item_id=superseded.id,
                        related_memory_item_id=item.id,
                        reason_code="user_stated_exact_match",
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
                self._add_event(
                    session,
                    user_id,
                    MemoryLifecycleEventType.CORRECTED,
                    memory_item_id=item.id,
                    related_memory_item_id=duplicate.id,
                    reason_code="matched_existing_user_statement",
                )
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
            replacement.supersedes_item_id = item.id
            self._add_creation_events(session, user_id, replacement, request)
            self._add_event(
                session,
                user_id,
                MemoryLifecycleEventType.CORRECTED,
                memory_item_id=item.id,
                related_memory_item_id=replacement.id,
                reason_code="user_correction",
            )
            if duplicate is not None:
                self._add_event(
                    session,
                    user_id,
                    MemoryLifecycleEventType.SUPERSEDED,
                    memory_item_id=duplicate.id,
                    related_memory_item_id=replacement.id,
                    reason_code="correction_replaced_model_inference",
                )
            await session.flush()
            return replacement.id

    async def record_prompt_use(self, user_id: UUID, memory_item_ids: Sequence[UUID]) -> int:
        unique_ids = tuple(dict.fromkeys(memory_item_ids))
        if not unique_ids:
            return 0
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._required_active_user(session, user_id, for_update=True)
            consent = await session.get(OracleMemoryConsent, user_id, with_for_update=True)
            if not self._permits_memory(consent):
                return 0
            items = list(
                (
                    await session.scalars(
                        select(OracleMemoryItem)
                        .where(
                            OracleMemoryItem.user_id == user_id,
                            OracleMemoryItem.id.in_(unique_ids),
                            OracleMemoryItem.status == MemoryItemStatus.ACTIVE.value,
                        )
                        .order_by(OracleMemoryItem.id)
                        .with_for_update()
                    )
                ).all()
            )
            for item in items:
                item.use_count += 1
                item.last_used_at = now
                self._add_event(
                    session,
                    user_id,
                    MemoryLifecycleEventType.USED,
                    memory_item_id=item.id,
                    reason_code="selected_for_prompt",
                )
            await session.flush()
            return len(items)

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

    async def reconcile_retention(self, user_id: UUID) -> int:
        async with self._sessions.begin() as session:
            await self._required_active_user(session, user_id, for_update=True)
            consent = await session.get(OracleMemoryConsent, user_id, with_for_update=True)
            if not self._permits_memory(consent):
                raise MemoryConsentRequiredError("explicit oracle memory consent is required")
            retired = await self._retire_decayed_inferences(session, user_id)
            await self._enforce_existing_limits(session, user_id)
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

    async def usefulness_summary(self, user_id: UUID) -> MemoryUsefulnessSummary:
        observed_at = datetime.now(UTC)
        async with self._sessions() as session:
            await self._required_active_user(session, user_id)
            rows = (
                await session.execute(
                    select(OracleMemoryEvent.event_type, func.count())
                    .where(OracleMemoryEvent.user_id == user_id)
                    .group_by(OracleMemoryEvent.event_type)
                )
            ).all()
        counts = {event_type: int(count) for event_type, count in rows}
        return MemoryUsefulnessSummary(
            created_count=counts.get(MemoryLifecycleEventType.CREATED.value, 0),
            extracted_count=counts.get(MemoryLifecycleEventType.EXTRACTED.value, 0),
            used_count=counts.get(MemoryLifecycleEventType.USED.value, 0),
            deleted_count=counts.get(MemoryLifecycleEventType.DELETED.value, 0),
            corrected_count=counts.get(MemoryLifecycleEventType.CORRECTED.value, 0),
            deduplicated_count=counts.get(MemoryLifecycleEventType.DEDUPLICATED.value, 0),
            superseded_count=counts.get(MemoryLifecycleEventType.SUPERSEDED.value, 0),
            decayed_count=counts.get(MemoryLifecycleEventType.DECAYED.value, 0),
            capacity_retired_count=counts.get(
                MemoryLifecycleEventType.CAPACITY_RETIRED.value,
                0,
            ),
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
        losers: list[tuple[OracleMemoryItem, OracleMemoryItem]] = []
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
                losers.append((current, item))
                fingerprints[fingerprint] = item
            else:
                losers.append((item, current))
        if reconcile and losers:
            now = datetime.now(UTC)
            await self._purge_items(session, [loser for loser, _ in losers], now)
            for loser, winner in losers:
                self._add_event(
                    session,
                    user_id,
                    MemoryLifecycleEventType.DEDUPLICATED,
                    memory_item_id=loser.id,
                    related_memory_item_id=winner.id,
                    reason_code="exact_keyed_identity",
                )
        return fingerprints, len(losers)

    async def _ensure_capacity(
        self,
        session: AsyncSession,
        user_id: UUID,
        incoming_basis: MemoryClaimBasis,
    ) -> bool:
        await self._retire_decayed_inferences(session, user_id)
        items = await self._active_items_locked(session, user_id)
        active_count = len(items)
        inferred_count = sum(
            item.claim_basis == MemoryClaimBasis.MODEL_INFERRED.value for item in items
        )
        needs_active_slot = active_count >= self._max_active_items
        needs_inferred_slot = (
            incoming_basis is MemoryClaimBasis.MODEL_INFERRED
            and inferred_count >= self._max_model_inferred_items
        )
        if not needs_active_slot and not needs_inferred_slot:
            return True

        candidates = sorted(
            (
                item
                for item in items
                if item.claim_basis == MemoryClaimBasis.MODEL_INFERRED.value
            ),
            key=self._retention_key,
        )
        retired: list[OracleMemoryItem] = []
        for item in candidates:
            if active_count < self._max_active_items and (
                incoming_basis is not MemoryClaimBasis.MODEL_INFERRED
                or inferred_count < self._max_model_inferred_items
            ):
                break
            retired.append(item)
            active_count -= 1
            inferred_count -= 1
        if retired:
            now = datetime.now(UTC)
            await self._purge_items(session, retired, now)
            for item in retired:
                self._add_event(
                    session,
                    user_id,
                    MemoryLifecycleEventType.CAPACITY_RETIRED,
                    memory_item_id=item.id,
                    reason_code="model_inferred_capacity",
                )
        return active_count < self._max_active_items and (
            incoming_basis is not MemoryClaimBasis.MODEL_INFERRED
            or inferred_count < self._max_model_inferred_items
        )

    async def _retire_decayed_inferences(
        self,
        session: AsyncSession,
        user_id: UUID,
    ) -> int:
        now = datetime.now(UTC)
        items = await self._active_items_locked(session, user_id)
        decayed = [
            item
            for item in items
            if item.claim_basis == MemoryClaimBasis.MODEL_INFERRED.value
            and item.confidence_milli <= self._decay_confidence_milli
            and memory_is_stale(MemoryKind(item.kind), item.created_at, now=now)
        ]
        if not decayed:
            return 0
        await self._purge_items(session, decayed, now)
        for item in decayed:
            self._add_event(
                session,
                user_id,
                MemoryLifecycleEventType.DECAYED,
                memory_item_id=item.id,
                reason_code="stale_low_confidence_model_inferred",
            )
        return len(decayed)

    async def _enforce_existing_limits(self, session: AsyncSession, user_id: UUID) -> int:
        items = await self._active_items_locked(session, user_id)
        active_count = len(items)
        inferred_count = sum(
            item.claim_basis == MemoryClaimBasis.MODEL_INFERRED.value for item in items
        )
        candidates = sorted(
            (
                item
                for item in items
                if item.claim_basis == MemoryClaimBasis.MODEL_INFERRED.value
            ),
            key=self._retention_key,
        )
        retired: list[OracleMemoryItem] = []
        for item in candidates:
            if (
                active_count <= self._max_active_items
                and inferred_count <= self._max_model_inferred_items
            ):
                break
            retired.append(item)
            active_count -= 1
            inferred_count -= 1
        if retired:
            now = datetime.now(UTC)
            await self._purge_items(session, retired, now)
            for item in retired:
                self._add_event(
                    session,
                    user_id,
                    MemoryLifecycleEventType.CAPACITY_RETIRED,
                    memory_item_id=item.id,
                    reason_code="reconcile_existing_limits",
                )
        return len(retired)

    async def _purge_with_events(
        self,
        session: AsyncSession,
        user_id: UUID,
        items: list[OracleMemoryItem],
        now: datetime,
        event_type: MemoryLifecycleEventType,
        *,
        reason_code: str,
    ) -> None:
        await self._purge_items(session, items, now)
        for item in items:
            self._add_event(
                session,
                user_id,
                event_type,
                memory_item_id=item.id,
                reason_code=reason_code,
            )

    def _add_creation_events(
        self,
        session: AsyncSession,
        user_id: UUID,
        item: OracleMemoryItem,
        request: MemoryCreateRequest,
    ) -> None:
        self._add_event(
            session,
            user_id,
            MemoryLifecycleEventType.CREATED,
            memory_item_id=item.id,
            reason_code=request.source_type.value,
        )
        if request.source_type is MemorySourceType.READING_DERIVED:
            self._add_event(
                session,
                user_id,
                MemoryLifecycleEventType.EXTRACTED,
                memory_item_id=item.id,
                reason_code=request.extraction_version,
            )

    @staticmethod
    def _add_event(
        session: AsyncSession,
        user_id: UUID,
        event_type: MemoryLifecycleEventType,
        *,
        memory_item_id: UUID | None = None,
        related_memory_item_id: UUID | None = None,
        reason_code: str | None = None,
    ) -> None:
        session.add(
            OracleMemoryEvent(
                user_id=user_id,
                memory_item_id=memory_item_id,
                related_memory_item_id=related_memory_item_id,
                event_type=event_type.value,
                reason_code=reason_code,
            )
        )

    @staticmethod
    def _retention_key(item: OracleMemoryItem) -> tuple[int, int, datetime, str]:
        return (
            item.use_count,
            item.confidence_milli,
            item.last_used_at or item.created_at,
            str(item.id),
        )

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
