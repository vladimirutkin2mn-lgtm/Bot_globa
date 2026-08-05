"""Persistence boundary for independent oracle readings."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.reading_models import Persona, Reading, ReadingPrivateContent, ReadingSymbol
from app.domain.reading import (
    ReadingAccess,
    ReadingDraftRequest,
    ReadingStatus,
    ReadingSymbolInput,
    ensure_reading_transition,
)
from app.services.sensitive_content import ContentPurpose, SensitiveContentCipher


@dataclass(frozen=True)
class ReadingSource:
    question: str
    context: str | None


class SqlAlchemyReadingRepository:
    """Own all Reading SQL and encrypted content persistence in one boundary."""

    def __init__(
        self,
        session: AsyncSession,
        cipher: SensitiveContentCipher,
        retention_days: int = 30,
    ) -> None:
        self._session = session
        self._cipher = cipher
        self._retention_days = retention_days

    async def enabled_persona(self, code: str) -> Persona | None:
        return cast(
            Persona | None,
            await self._session.scalar(
                select(Persona).where(Persona.code == code, Persona.enabled.is_(True))
            ),
        )

    async def create_draft(
        self,
        user_id: UUID,
        persona: Persona,
        request: ReadingDraftRequest,
    ) -> Reading:
        user = await self._session.scalar(
            select(User).where(User.id == user_id, User.privacy_status == "active")
        )
        if user is None:
            raise LookupError("active reading user not found")
        reading = Reading(
            user_id=user_id,
            persona_id=persona.id,
            topic=request.topic,
            status=ReadingStatus.DRAFT.value,
            access_level=ReadingAccess.NONE.value,
            cost_units=request.cost_units,
            engine_version=request.engine_version,
            prompt_version=request.prompt_version,
            schema_version=request.schema_version,
        )
        self._session.add(reading)
        await self._session.flush()
        private = ReadingPrivateContent(
            reading_id=reading.id,
            question_ciphertext=self._cipher.encrypt_json(
                ContentPurpose.READING_QUESTION, request.question
            ),
            context_ciphertext=(
                self._cipher.encrypt_json(ContentPurpose.READING_CONTEXT, request.context)
                if request.context is not None
                else None
            ),
            question_format_version=1,
            context_format_version=1 if request.context is not None else None,
            content_delete_after=datetime.now(UTC) + timedelta(days=self._retention_days),
        )
        self._session.add(private)
        await self._session.flush()
        return reading

    async def get_owned(
        self,
        reading_id: UUID,
        user_id: UUID,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> Reading | None:
        statement = (
            select(Reading)
            .join(User, User.id == Reading.user_id)
            .where(
                Reading.id == reading_id,
                Reading.user_id == user_id,
                User.privacy_status == "active",
            )
        )
        if not include_deleted:
            statement = statement.where(Reading.status != ReadingStatus.DELETED.value)
        if for_update:
            statement = statement.with_for_update(of=Reading)
        return cast(Reading | None, await self._session.scalar(statement))

    async def load_source(self, reading_id: UUID, user_id: UUID) -> ReadingSource | None:
        row = await self._session.scalar(
            select(ReadingPrivateContent)
            .join(Reading, Reading.id == ReadingPrivateContent.reading_id)
            .join(User, User.id == Reading.user_id)
            .where(
                Reading.id == reading_id,
                Reading.user_id == user_id,
                Reading.status != ReadingStatus.DELETED.value,
                User.privacy_status == "active",
            )
        )
        if row is None or row.question_ciphertext is None:
            return None
        question = self._cipher.decrypt_json(
            ContentPurpose.READING_QUESTION, row.question_ciphertext
        )
        context = (
            self._cipher.decrypt_json(ContentPurpose.READING_CONTEXT, row.context_ciphertext)
            if row.context_ciphertext is not None
            else None
        )
        if not isinstance(question, str) or (context is not None and not isinstance(context, str)):
            raise ValueError("invalid decrypted reading source shape")
        return ReadingSource(question=question, context=context)

    async def load_result(self, reading_id: UUID, user_id: UUID) -> dict[str, object] | None:
        row = await self._session.scalar(
            select(ReadingPrivateContent)
            .join(Reading, Reading.id == ReadingPrivateContent.reading_id)
            .join(User, User.id == Reading.user_id)
            .where(
                Reading.id == reading_id,
                Reading.user_id == user_id,
                Reading.status.in_(
                    (ReadingStatus.PREVIEW_READY.value, ReadingStatus.FULL_READY.value)
                ),
                User.privacy_status == "active",
            )
        )
        if row is None or row.result_ciphertext is None:
            return None
        value = self._cipher.decrypt_json(ContentPurpose.READING_RESULT, row.result_ciphertext)
        if not isinstance(value, dict):
            raise ValueError("invalid decrypted reading result shape")
        return cast(dict[str, object], value)

    async def start_generation(self, reading_id: UUID, user_id: UUID) -> Reading:
        reading = await self._required_locked(reading_id, user_id)
        current = ReadingStatus(reading.status)
        ensure_reading_transition(current, ReadingStatus.GENERATING)
        reading.status = ReadingStatus.GENERATING.value
        reading.access_level = ReadingAccess.NONE.value
        reading.generation_started_at = datetime.now(UTC)
        reading.generated_at = None
        reading.failure_code = None
        await self._session.flush()
        return reading

    async def complete_generation(
        self,
        reading_id: UUID,
        user_id: UUID,
        result: dict[str, object],
        symbols: list[ReadingSymbolInput],
        *,
        full: bool,
    ) -> Reading:
        reading = await self._required_locked(reading_id, user_id)
        target = ReadingStatus.FULL_READY if full else ReadingStatus.PREVIEW_READY
        ensure_reading_transition(ReadingStatus(reading.status), target)
        self._validate_symbols(symbols)
        private = await self._private_row(reading.id)
        private.result_ciphertext = self._cipher.encrypt_json(ContentPurpose.READING_RESULT, result)
        private.result_format_version = 1
        private.content_deleted_at = None
        await self._session.execute(
            delete(ReadingSymbol).where(ReadingSymbol.reading_id == reading.id)
        )
        self._session.add_all(
            [
                ReadingSymbol(
                    reading_id=reading.id,
                    ordinal=index,
                    symbol_id=symbol.symbol_id,
                    position=symbol.position,
                    orientation=symbol.orientation.value,
                    catalog_version=symbol.catalog_version,
                )
                for index, symbol in enumerate(symbols)
            ]
        )
        reading.status = target.value
        reading.access_level = ReadingAccess.FULL.value if full else ReadingAccess.PREVIEW.value
        reading.generated_at = datetime.now(UTC)
        reading.failure_code = None
        await self._session.flush()
        return reading

    async def promote_full_access(self, reading_id: UUID, user_id: UUID) -> Reading:
        reading = await self._required_locked(reading_id, user_id)
        ensure_reading_transition(ReadingStatus(reading.status), ReadingStatus.FULL_READY)
        private = await self._private_row(reading.id)
        if private.result_ciphertext is None:
            raise RuntimeError("reading result is unavailable")
        reading.status = ReadingStatus.FULL_READY.value
        reading.access_level = ReadingAccess.FULL.value
        await self._session.flush()
        return reading

    async def fail_generation(self, reading_id: UUID, user_id: UUID, failure_code: str) -> Reading:
        reading = await self._required_locked(reading_id, user_id)
        ensure_reading_transition(ReadingStatus(reading.status), ReadingStatus.FAILED)
        reading.status = ReadingStatus.FAILED.value
        reading.access_level = ReadingAccess.NONE.value
        reading.generated_at = None
        reading.failure_code = failure_code
        await self._session.flush()
        return reading

    async def delete_owned(self, reading_id: UUID, user_id: UUID) -> Reading:
        reading = await self._required_locked(reading_id, user_id)
        ensure_reading_transition(ReadingStatus(reading.status), ReadingStatus.DELETED)
        private = await self._private_row(reading.id)
        private.question_ciphertext = None
        private.context_ciphertext = None
        private.result_ciphertext = None
        private.content_deleted_at = datetime.now(UTC)
        await self._session.execute(
            delete(ReadingSymbol).where(ReadingSymbol.reading_id == reading.id)
        )
        reading.status = ReadingStatus.DELETED.value
        reading.access_level = ReadingAccess.NONE.value
        reading.generated_at = None
        reading.failure_code = None
        reading.deleted_at = datetime.now(UTC)
        await self._session.flush()
        return reading

    async def _required_locked(self, reading_id: UUID, user_id: UUID) -> Reading:
        reading = await self.get_owned(reading_id, user_id, for_update=True)
        if reading is None:
            raise LookupError("owned reading not found")
        return reading

    async def _private_row(self, reading_id: UUID) -> ReadingPrivateContent:
        row = await self._session.get(ReadingPrivateContent, reading_id)
        if row is None:
            raise RuntimeError("reading private content is unavailable")
        return row

    @staticmethod
    def _validate_symbols(symbols: list[ReadingSymbolInput]) -> None:
        positions = [symbol.position for symbol in symbols]
        if len(positions) != len(set(positions)):
            raise ValueError("duplicate reading symbol position")
