"""Transactional explicit-consent service for encrypted oracle memory."""

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
from app.db.models import User
from app.db.reading_models import Persona, Reading
from app.domain.oracle_memory import (
    CURRENT_MEMORY_CONSENT_VERSION,
    MemoryConsentStatus,
    MemoryConsentView,
    MemoryCreateRequest,
    MemoryItemStatus,
    MemoryItemView,
    MemoryKind,
    MemorySourceType,
)
from app.domain.reading import ReadingStatus
from app.services.sensitive_content import ContentPurpose, SensitiveContentCipher


class MemoryConsentRequiredError(PermissionError):
    """Safe error raised when memory use has not been explicitly authorized."""


class MemoryProvenanceError(ValueError):
    """Safe error raised for invalid ownership or provenance metadata."""


class OracleMemoryService:
    """Serialize consent changes and keep private values encrypted at rest."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: SensitiveContentCipher,
        *,
        consent_version: str = CURRENT_MEMORY_CONSENT_VERSION,
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher
        self._consent_version = consent_version

    async def consent_state(self, user_id: UUID) -> MemoryConsentView | None:
        async with self._sessions() as session:
            row = await session.get(OracleMemoryConsent, user_id)
            return self._view(row) if row is not None else None

    async def grant_consent(self, user_id: UUID) -> MemoryConsentView:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._required_active_user(session, user_id, for_update=True)
            consent = await session.get(OracleMemoryConsent, user_id, with_for_update=True)
            if consent is None:
                consent = OracleMemoryConsent(
                    user_id=user_id,
                    status=MemoryConsentStatus.GRANTED.value,
                    consent_version=self._consent_version,
                    accepted_at=now,
                    revoked_at=None,
                )
                session.add(consent)
            elif not (
                consent.status == MemoryConsentStatus.GRANTED.value
                and consent.consent_version == self._consent_version
            ):
                consent.status = MemoryConsentStatus.GRANTED.value
                consent.consent_version = self._consent_version
                consent.accepted_at = now
                consent.revoked_at = None
            await session.flush()
            return self._view(consent)

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

            items = list(
                (
                    await session.scalars(
                        select(OracleMemoryItem)
                        .where(
                            OracleMemoryItem.user_id == user_id,
                            OracleMemoryItem.status == MemoryItemStatus.ACTIVE.value,
                        )
                        .order_by(OracleMemoryItem.id)
                        .with_for_update()
                    )
                ).all()
            )
            await self._purge_items(session, items, now)
            await session.flush()
            return self._view(consent)

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

            item = OracleMemoryItem(
                user_id=user_id,
                kind=request.kind.value,
                status=MemoryItemStatus.ACTIVE.value,
                confidence_milli=request.confidence_milli,
                source_type=request.source_type.value,
                source_reading_id=request.source_reading_id,
                source_persona_code=source_persona_code,
                extraction_version=request.extraction_version,
            )
            session.add(item)
            await session.flush()
            session.add(
                OracleMemoryPrivateContent(
                    memory_item_id=item.id,
                    value_ciphertext=self._cipher.encrypt_json(
                        ContentPurpose.ORACLE_MEMORY_VALUE,
                        request.value,
                    ),
                    value_format_version=1,
                    content_deleted_at=None,
                )
            )
            await session.flush()
            return item

    async def list_active(self, user_id: UUID) -> list[MemoryItemView]:
        async with self._sessions() as session:
            user = await self._required_active_user(session, user_id)
            consent = await session.get(OracleMemoryConsent, user.id)
            if not self._permits_memory(consent):
                return []
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
                        .order_by(OracleMemoryItem.created_at, OracleMemoryItem.id)
                    )
                ).all()
            )
            views: list[MemoryItemView] = []
            for item, private in rows:
                assert private.value_ciphertext is not None
                value = self._cipher.decrypt_json(
                    ContentPurpose.ORACLE_MEMORY_VALUE,
                    private.value_ciphertext,
                )
                if not isinstance(value, str):
                    raise ValueError("invalid decrypted oracle memory shape")
                views.append(
                    MemoryItemView(
                        id=item.id,
                        kind=MemoryKind(item.kind),
                        value=value,
                        confidence_milli=item.confidence_milli,
                        source_type=MemorySourceType(item.source_type),
                        source_reading_id=item.source_reading_id,
                        source_persona_code=item.source_persona_code,
                        extraction_version=item.extraction_version,
                        created_at=item.created_at,
                    )
                )
            return views

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
            await self._purge_items(session, [item], now)
            await session.flush()
            return True

    async def _validate_reading_provenance(
        self,
        session: AsyncSession,
        user_id: UUID,
        reading_id: UUID | None,
        requested_persona_code: str | None,
    ) -> str:
        if reading_id is None:
            raise MemoryProvenanceError("reading provenance is required")
        row = (
            await session.execute(
                select(Reading, Persona)
                .join(Persona, Persona.id == Reading.persona_id)
                .where(
                    Reading.id == reading_id,
                    Reading.user_id == user_id,
                    Reading.status != ReadingStatus.DELETED.value,
                )
            )
        ).one_or_none()
        if row is None:
            raise MemoryProvenanceError("owned source reading is unavailable")
        _, persona = row
        if requested_persona_code is not None and requested_persona_code != persona.code:
            raise MemoryProvenanceError("source persona does not match reading provenance")
        return persona.code

    async def _purge_items(
        self,
        session: AsyncSession,
        items: list[OracleMemoryItem],
        now: datetime,
    ) -> None:
        if not items:
            return
        ids = [item.id for item in items]
        private_rows = list(
            (
                await session.scalars(
                    select(OracleMemoryPrivateContent)
                    .where(OracleMemoryPrivateContent.memory_item_id.in_(ids))
                    .order_by(OracleMemoryPrivateContent.memory_item_id)
                    .with_for_update()
                )
            ).all()
        )
        for private in private_rows:
            private.value_ciphertext = None
            private.value_format_version = None
            private.content_deleted_at = now
        for item in items:
            item.status = MemoryItemStatus.DELETED.value
            item.deleted_at = now

    async def _required_active_user(
        self,
        session: AsyncSession,
        user_id: UUID,
        *,
        for_update: bool = False,
    ) -> User:
        statement = select(User).where(User.id == user_id, User.privacy_status == "active")
        if for_update:
            statement = statement.with_for_update(of=User)
        user = cast(User | None, await session.scalar(statement))
        if user is None:
            raise LookupError("active oracle memory user not found")
        return user

    def _permits_memory(self, consent: OracleMemoryConsent | None) -> bool:
        return (
            consent is not None
            and consent.status == MemoryConsentStatus.GRANTED.value
            and consent.consent_version == self._consent_version
        )

    @staticmethod
    def _view(consent: OracleMemoryConsent) -> MemoryConsentView:
        return MemoryConsentView(
            status=MemoryConsentStatus(consent.status),
            consent_version=consent.consent_version,
            accepted_at=consent.accepted_at,
            revoked_at=consent.revoked_at,
        )
