"""Transactional PostgreSQL store for the reading generation pipeline."""

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.reading_models import Persona, ReadingSymbol
from app.domain.reading import ReadingStatus, ReadingSymbolInput, SymbolOrientation
from app.domain.reading_generation import (
    ReadingGenerationClaim,
    ReadingGenerationClaimStatus,
    ReadingGenerationContext,
    ReadingGenerationFinalizeStatus,
    StoredReadingResult,
)
from app.repositories.readings import SqlAlchemyReadingRepository
from app.services.sensitive_content import SensitiveContentCipher


class SqlAlchemyReadingGenerationStore:
    """Claim and finalize generation without holding a DB transaction during LLM calls."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: SensitiveContentCipher,
        retention_days: int = 30,
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher
        self._retention_days = retention_days

    async def claim_preview(self, reading_id: UUID, user_id: UUID) -> ReadingGenerationClaim:
        async with self._sessions.begin() as session:
            active_user = await session.scalar(
                select(User)
                .where(User.id == user_id, User.privacy_status == "active")
                .with_for_update(of=User)
            )
            if active_user is None:
                return ReadingGenerationClaim(ReadingGenerationClaimStatus.NOT_FOUND)
            repository = self._repository(session)
            reading = await repository.get_owned(
                reading_id,
                user_id,
                for_update=True,
                include_deleted=True,
            )
            if reading is None:
                return ReadingGenerationClaim(ReadingGenerationClaimStatus.NOT_FOUND)
            status = ReadingStatus(reading.status)
            if status is ReadingStatus.DELETED:
                return ReadingGenerationClaim(ReadingGenerationClaimStatus.DELETED)
            if status is ReadingStatus.GENERATING:
                return ReadingGenerationClaim(ReadingGenerationClaimStatus.ALREADY_PROCESSING)
            if status in {ReadingStatus.PREVIEW_READY, ReadingStatus.FULL_READY}:
                try:
                    payload = await repository.load_result(reading_id, user_id)
                    symbols = await self._load_symbols(session, reading_id)
                except (TypeError, ValueError):
                    return ReadingGenerationClaim(ReadingGenerationClaimStatus.CORRUPTED_RESULT)
                if payload is None:
                    return ReadingGenerationClaim(ReadingGenerationClaimStatus.CORRUPTED_RESULT)
                return ReadingGenerationClaim(
                    ReadingGenerationClaimStatus.READY,
                    ready=StoredReadingResult(payload, symbols),
                )
            if status not in {ReadingStatus.DRAFT, ReadingStatus.FAILED}:
                return ReadingGenerationClaim(ReadingGenerationClaimStatus.NOT_READY)
            persona = cast("Persona | None", await session.get(Persona, reading.persona_id))
            if persona is None or not persona.enabled:
                return ReadingGenerationClaim(ReadingGenerationClaimStatus.PERSONA_DISABLED)
            try:
                source = await repository.load_source(reading_id, user_id)
            except (TypeError, ValueError):
                return ReadingGenerationClaim(ReadingGenerationClaimStatus.NOT_READY)
            if source is None:
                return ReadingGenerationClaim(ReadingGenerationClaimStatus.NOT_READY)
            await repository.start_generation(reading_id, user_id)
            return ReadingGenerationClaim(
                ReadingGenerationClaimStatus.CLAIMED,
                context=ReadingGenerationContext(
                    reading_id=reading.id,
                    user_id=reading.user_id,
                    persona_code=persona.code,
                    topic=reading.topic,
                    question=source.question,
                    context=source.context,
                    engine_version=reading.engine_version,
                    prompt_version=reading.prompt_version,
                    schema_version=reading.schema_version,
                ),
            )

    async def complete_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
        result: dict[str, object],
        symbols: tuple[ReadingSymbolInput, ...],
    ) -> ReadingGenerationFinalizeStatus:
        async with self._sessions.begin() as session:
            repository = self._repository(session)
            reading = await repository.get_owned(
                reading_id,
                user_id,
                for_update=True,
                include_deleted=True,
            )
            if reading is None:
                return ReadingGenerationFinalizeStatus.NOT_FOUND
            status = ReadingStatus(reading.status)
            if status is ReadingStatus.DELETED:
                return ReadingGenerationFinalizeStatus.DELETED
            if status is not ReadingStatus.GENERATING:
                return ReadingGenerationFinalizeStatus.STATE_CONFLICT
            await repository.complete_generation(
                reading_id,
                user_id,
                result,
                list(symbols),
                full=False,
            )
            return ReadingGenerationFinalizeStatus.COMPLETED

    async def fail_generation(
        self,
        reading_id: UUID,
        user_id: UUID,
        failure_code: str,
    ) -> ReadingGenerationFinalizeStatus:
        async with self._sessions.begin() as session:
            repository = self._repository(session)
            reading = await repository.get_owned(
                reading_id,
                user_id,
                for_update=True,
                include_deleted=True,
            )
            if reading is None:
                return ReadingGenerationFinalizeStatus.NOT_FOUND
            status = ReadingStatus(reading.status)
            if status is ReadingStatus.DELETED:
                return ReadingGenerationFinalizeStatus.DELETED
            if status is ReadingStatus.FAILED and reading.failure_code == failure_code:
                return ReadingGenerationFinalizeStatus.COMPLETED
            if status is not ReadingStatus.GENERATING:
                return ReadingGenerationFinalizeStatus.STATE_CONFLICT
            await repository.fail_generation(reading_id, user_id, failure_code)
            return ReadingGenerationFinalizeStatus.COMPLETED

    def _repository(self, session: AsyncSession) -> SqlAlchemyReadingRepository:
        return SqlAlchemyReadingRepository(
            session,
            self._cipher,
            retention_days=self._retention_days,
        )

    @staticmethod
    async def _load_symbols(
        session: AsyncSession,
        reading_id: UUID,
    ) -> tuple[ReadingSymbolInput, ...]:
        rows = (
            await session.scalars(
                select(ReadingSymbol)
                .where(ReadingSymbol.reading_id == reading_id)
                .order_by(ReadingSymbol.ordinal)
            )
        ).all()
        return tuple(
            ReadingSymbolInput(
                symbol_id=row.symbol_id,
                position=row.position,
                orientation=SymbolOrientation(row.orientation),
                catalog_version=row.catalog_version,
            )
            for row in rows
        )
