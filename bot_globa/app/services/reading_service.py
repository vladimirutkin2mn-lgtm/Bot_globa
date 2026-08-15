"""Transactional application service for the independent Reading domain."""

import logging
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.reading_models import Reading
from app.domain.reading import ReadingDraftRequest, ReadingSymbolInput
from app.providers.analytics import OracleProductEvent
from app.repositories.readings import ReadingSource, SqlAlchemyReadingRepository
from app.services.oracle_product_analytics import (
    OracleAnalyticsValue,
    OracleProductAnalytics,
)
from app.services.oracle_release_controls import (
    OracleReleaseControls,
    OracleReleaseDecisionCode,
)
from app.services.sensitive_content import SensitiveContentCipher

logger = logging.getLogger(__name__)


class PersonaUnavailableError(LookupError):
    """The requested persona does not exist or is disabled."""


class OracleReleaseUnavailableError(PersonaUnavailableError):
    """A limited-release control denied a new Reading without exposing private input."""

    def __init__(self, reason: OracleReleaseDecisionCode) -> None:
        super().__init__("reading persona is unavailable")
        self.reason = reason


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
        analytics: OracleProductAnalytics | None = None,
        release_controls: OracleReleaseControls | None = None,
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher
        self._retention_days = retention_days
        self._preview_entitlements = preview_entitlements
        self._analytics = analytics
        self._release_controls = release_controls

    async def create_draft(self, user_id: UUID, request: ReadingDraftRequest) -> Reading:
        async with self._sessions.begin() as session:
            if self._release_controls is not None:
                decision = await self._release_controls.authorize_draft(session, user_id, request)
                if not decision.allowed:
                    raise OracleReleaseUnavailableError(decision.code)
            repository = self._repository(session)
            persona = await repository.enabled_persona(request.persona_code)
            if persona is None:
                raise PersonaUnavailableError("reading persona is unavailable")
            reading = await repository.create_draft(user_id, persona, request)
        await self._track(
            user_id,
            OracleProductEvent.READING_STARTED,
            {
                "reading_id": reading.id,
                "persona_code": request.persona_code,
                "topic_code": request.topic,
                "engine_version": request.engine_version,
                "prompt_version": request.prompt_version,
                "schema_version": request.schema_version,
                "symbol_set_code": request.symbol_set_code,
            },
        )
        return reading

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

    async def fail_generation(
        self,
        reading_id: UUID,
        user_id: UUID,
        failure_code: str,
    ) -> Reading:
        async with self._sessions.begin() as session:
            return await self._repository(session).fail_generation(
                reading_id,
                user_id,
                failure_code,
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

    async def load_symbol_contract(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> tuple[str, str] | None:
        """Return the frozen engine and symbol-set versions for deterministic replay."""

        async with self._sessions() as session:
            reading = await self._repository(session).get_owned(reading_id, user_id)
            if reading is None:
                return None
            return reading.engine_version, reading.symbol_set_code

    def _repository(self, session: AsyncSession) -> SqlAlchemyReadingRepository:
        return SqlAlchemyReadingRepository(
            session,
            self._cipher,
            retention_days=self._retention_days,
        )

    async def _track(
        self,
        user_id: UUID,
        event: OracleProductEvent,
        properties: dict[str, OracleAnalyticsValue | None],
    ) -> None:
        if self._analytics is None:
            return
        try:
            await self._analytics.track(user_id, event, properties)
        except Exception:
            logger.warning("oracle_analytics_failed event=%s", event.value)
