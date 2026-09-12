"""Idempotent PostgreSQL implementation of the analytics boundary."""

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.analytics import AnalyticsEvent
from app.observability.context import correlation_id_for_event
from app.observability.settings import ObservabilitySettings
from app.providers.analytics import (
    AnalyticsClient,
    NoOpAnalyticsClient,
    ResilientAnalyticsClient,
    event_identity,
    validate_event_properties,
)
from app.providers.numa_product_analytics import (
    ProductFlow,
    ProductFunnelEvent,
    is_numa_group_event,
    is_numa_product_event,
    numa_product_event_identity,
    validate_numa_group_event,
    validate_numa_product_event,
)
from app.providers.numa_reading_projection import project_personal_reading_event


class PostgresAnalyticsClient:
    """Store only allow-listed metadata and suppress duplicate transitions."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def track(
        self, user_id: str | None, event: str, properties: Mapping[str, str] | None = None
    ) -> None:
        correlation_id = correlation_id_for_event()
        if is_numa_group_event(event):
            safe_properties = validate_numa_group_event(event, properties)
            subject_id = None
            idempotency_key = f"{event}:{correlation_id}"
        elif is_numa_product_event(event):
            safe_properties = validate_numa_product_event(event, properties)
            subject_id, idempotency_key = numa_product_event_identity(
                user_id, event, safe_properties
            )
        else:
            safe_properties = validate_event_properties(event, properties)
            subject_id, idempotency_key = event_identity(
                user_id, event, safe_properties, correlation_id
            )
        async with self._sessions.begin() as session:
            await self._insert(
                session,
                event=event,
                subject_id=subject_id,
                properties=safe_properties,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
            projected = project_personal_reading_event(
                event,
                safe_properties,
                subject_id=subject_id,
            )
            if projected is not None:
                _, default_projected_properties = projected
                reading_id = default_projected_properties["entity_id"]
                attribution = await self._reading_attribution(session, subject_id, reading_id)
                if attribution is None:
                    attribution = await self._latest_personal_entry(session, subject_id)
                if attribution is not None:
                    projected = project_personal_reading_event(
                        event,
                        safe_properties,
                        attribution,
                        subject_id=subject_id,
                    )
                if projected is None:
                    return
                projected_event, projected_properties = projected
                projected_subject, projected_key = numa_product_event_identity(
                    user_id,
                    projected_event,
                    projected_properties,
                )
                await self._insert(
                    session,
                    event=projected_event,
                    subject_id=projected_subject,
                    properties=projected_properties,
                    idempotency_key=projected_key,
                    correlation_id=correlation_id,
                )

    @staticmethod
    async def _insert(
        session: AsyncSession,
        *,
        event: str,
        subject_id: str | None,
        properties: Mapping[str, str],
        idempotency_key: str,
        correlation_id: str,
    ) -> None:
        await session.execute(
            insert(AnalyticsEvent)
            .values(
                event_name=event,
                subject_id=subject_id,
                properties=dict(properties),
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
            .on_conflict_do_nothing(index_elements=[AnalyticsEvent.idempotency_key])
        )

    @staticmethod
    async def _reading_attribution(
        session: AsyncSession,
        subject_id: str | None,
        reading_id: str,
    ) -> Mapping[str, str] | None:
        """Reuse the source captured when this reading first entered the typed funnel."""

        if subject_id is None:
            return None
        event = await session.scalar(
            select(AnalyticsEvent)
            .where(
                AnalyticsEvent.event_name == ProductFunnelEvent.QUESTION_ACCEPTED.value,
                AnalyticsEvent.subject_id == subject_id,
                AnalyticsEvent.properties.contains({"entity_id": reading_id}),
            )
            .order_by(AnalyticsEvent.created_at.desc())
            .limit(1)
        )
        if event is None or event.properties.get("flow") != ProductFlow.PERSONAL.value:
            return None
        return event.properties

    @staticmethod
    async def _latest_personal_entry(
        session: AsyncSession,
        subject_id: str | None,
    ) -> Mapping[str, str] | None:
        if subject_id is None:
            return None
        entries = await session.scalars(
            select(AnalyticsEvent)
            .where(
                AnalyticsEvent.event_name == ProductFunnelEvent.ENTRY.value,
                AnalyticsEvent.subject_id == subject_id,
            )
            .order_by(AnalyticsEvent.created_at.desc())
            .limit(50)
        )
        for entry in entries:
            if entry.properties.get("flow") == ProductFlow.PERSONAL.value:
                return entry.properties
        return None


def create_analytics_client(
    sessions: async_sessionmaker[AsyncSession], settings: ObservabilitySettings
) -> AnalyticsClient:
    """Compose one analytics provider for API and bot processes."""
    if settings.analytics_backend == "postgres":
        return ResilientAnalyticsClient(PostgresAnalyticsClient(sessions))
    return NoOpAnalyticsClient()
