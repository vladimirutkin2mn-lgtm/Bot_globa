"""Transactional application service for the independent Reading domain."""

from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.reading_models import Reading
from app.domain.reading import ReadingDraftRequest, ReadingSymbolInput
from app.repositories.readings import ReadingSource, SqlAlchemyReadingRepository
from app.services.sensitive_content import SensitiveContentCipher


class PersonaUnavailableError(LookupError):
    """The requested persona does not exist or is disabled."""


class ReadingPreviewReleaseService(Protocol):
    async def release_reading_preview(self, user_id: UUID, reading_id: UUID) -> object: ...


class ReadingService:
    """Expose Reading use cases without Telegram, billing or provider coupling."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: SensitiveContentCipher,
        retention_days: int = 30,
        preview_entitlements: ReadingPreviewReleaseService | None = None,
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher
        self._retention_days = retention_days
        self._preview_entitlements = preview_entitlements

    async def create_draft(self, user_id: UUID, request: ReadingDraftRequest) -> Reading:
        async with self._sessions.begin() as session:
  repository = self._repository(session)
  persona = await repository.enabled_persona(request.persona_code)
  if persona is None:
      raise PersonaUnavailableError("reading persona is unavailable")
  return await repository.create_draft(user_id, persona, request)

    async def start_generation(self, reading_id: UUID, user_id: UUID) -> Reading:
        async with self._sessions.begin() as session:
  return await self._repository(session).start_generation(reading_id, user_id)

    async def complete_preview(
        self,
        reading_id: UUID,
        user_id: UUID,
        result: dict[str, object],
        symbols: list[ReadingSymbolInput],
    ) -> Reading:
        async with self._sessions.begin() as session:
  return await self._repository(session).complete_generation(
      reading_id,
      user_id,
      result,
      symbols,
      full=False,
  )

    async def complete_full(
        self,
        reading_id: UUID,
        user_id: UUID,
        result: dict[str, object],
        symbols: list[ReadingSymbolInput],
        cost_units: int,
        transaction_id: UUID,
    ) -> Reading:
        await self.complete_preview(reading_id, user_id, result, symbols)
        return await self.promote_full_access(
  reading_id,
  user_id,
  cost_units,
  transaction_id,
        )

    async def promote_full_access(
        self,
        reading_id: UUID,
        user_id: UUID,
        cost_units: int,
        transaction_id: UUID,
    ) -> Reading:
        async with self._sessions.begin() as session:
  return await self._repository(session).promote_full_access(
      reading_id,
      user_id,
      cost_units,
      transaction_id,
  )

    async def fail_generation(self, reading_id: UUID, user_id: UUID, failure_code: str) -> Reading:
        async with self._sessions.begin() as session:
  return await self._repository(session).fail_generation(
      reading_id, user_id, failure_code
  )

    async def delete_owned(self, reading_id: UUID, user_id: UUID) -> Reading:
        async with self._sessions.begin() as session:
  reading = await self._repository(session).delete_owned(reading_id, user_id)
        if self._preview_entitlements is not None:
  await self._preview_entitlements.release_reading_preview(user_id, reading_id)
        return reading

    async def load_source(self, reading_id: UUID, user_id: UUID) -> ReadingSource | None:
        async with self._sessions() as session:
  return await self._repository(session).load_source(reading_id, user_id)

    async def load_result(self, reading_id: UUID, user_id: UUID) -> dict[str, object] | None:
        async with self._sessions() as session:
  return await self._repository(session).load_result(reading_id, user_id)

    def _repository(self, session: AsyncSession) -> SqlAlchemyReadingRepository:
        return SqlAlchemyReadingRepository(
  session,
  self._cipher,
  retention_days=self._retention_days,
        )
