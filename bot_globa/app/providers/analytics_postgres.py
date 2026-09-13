"""Idempotent PostgreSQL implementation of the analytics boundary."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.analytics import AnalyticsEvent
from app.observability.context import correlation_id_for_event
from app.observability.settings import ObservabilitySettings
from app.providers.analytics import (
    AnalyticsClient,
    AnalyticsContractError,
    NoOpAnalyticsClient,
    OracleProductEvent,
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

_FEEDBACK_STAGES = frozenset({"preview", "full", "unknown"})
_REPEAT_NAMESPACE = UUID("9de1a6b0-8fb9-499b-9226-fc1c587fa836")


class PostgresAnalyticsClient:
    """Store only allow-listed metadata and suppress duplicate transitions."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        test_user_ids: frozenset[str] = frozenset(),
    ) -> None:
        self._sessions = sessions
        self._test_user_ids = test_user_ids

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
            safe_properties = _mark_test_traffic(
                safe_properties,
                subject_id,
                self._test_user_ids,
            )
        elif event == OracleProductEvent.READING_FEEDBACK_SUBMITTED.value:
            safe_properties, subject_id, idempotency_key = _reading_feedback_event(
                user_id,
                properties,
            )
        else:
            safe_properties = validate_event_properties(event, properties)
            subject_id, idempotency_key = event_identity(
                user_id, event, safe_properties, correlation_id
            )
        async with self._sessions.begin() as session:
            first_entry = (
                await self._first_product_entry(session, subject_id)
                if event == ProductFunnelEvent.ENTRY.value and subject_id is not None
                else None
            )
            inserted = await self._insert(
                session,
                event=event,
                subject_id=subject_id,
                properties=safe_properties,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
            if inserted and first_entry is not None and subject_id is not None:
                repeat_properties = _repeat_activity_properties(
                    safe_properties,
                    subject_id,
                    first_entry.created_at,
                    datetime.now(UTC),
                )
                if repeat_properties is not None:
                    repeat_properties = validate_numa_product_event(
                        ProductFunnelEvent.REPEAT_ACTIVITY.value,
                        repeat_properties,
                    )
                    repeat_subject, repeat_key = numa_product_event_identity(
                        subject_id,
                        ProductFunnelEvent.REPEAT_ACTIVITY.value,
                        repeat_properties,
                    )
                    await self._insert(
                        session,
                        event=ProductFunnelEvent.REPEAT_ACTIVITY.value,
                        subject_id=repeat_subject,
                        properties=repeat_properties,
                        idempotency_key=repeat_key,
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
                projected_properties = _mark_test_traffic(
                    projected_properties,
                    projected_subject,
                    self._test_user_ids,
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
    ) -> bool:
        result = await session.execute(
            insert(AnalyticsEvent)
            .values(
                event_name=event,
                subject_id=subject_id,
                properties=dict(properties),
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
            .on_conflict_do_nothing(index_elements=[AnalyticsEvent.idempotency_key])
            .returning(AnalyticsEvent.id)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def _first_product_entry(
        session: AsyncSession,
        subject_id: str,
    ) -> AnalyticsEvent | None:
        return cast(
            "AnalyticsEvent | None",
            await session.scalar(
                select(AnalyticsEvent)
                .where(
                    AnalyticsEvent.event_name == ProductFunnelEvent.ENTRY.value,
                    AnalyticsEvent.subject_id == subject_id,
                )
                .order_by(AnalyticsEvent.created_at.asc())
                .limit(1)
            ),
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


def _reading_feedback_event(
    user_id: str | None,
    properties: Mapping[str, str] | None,
) -> tuple[dict[str, str], str, str]:
    """Validate attributed feedback and make the first reaction per reading stage durable."""

    supplied = dict(properties or {})
    reading_id = supplied.pop("reading_id", None)
    stage_code = supplied.pop("stage_code", None)
    safe = validate_event_properties(
        OracleProductEvent.READING_FEEDBACK_SUBMITTED.value,
        supplied,
    )
    if reading_id is None or stage_code not in _FEEDBACK_STAGES or user_id is None:
        raise AnalyticsContractError
    try:
        normalized_reading_id = str(UUID(reading_id))
        subject_id = str(UUID(user_id))
    except (TypeError, ValueError):
        raise AnalyticsContractError from None
    safe.update(
        {
            "reading_id": normalized_reading_id,
            "stage_code": stage_code,
        }
    )
    return (
        safe,
        subject_id,
        f"{OracleProductEvent.READING_FEEDBACK_SUBMITTED.value}:"
        f"{normalized_reading_id}:{stage_code}",
    )


def _mark_test_traffic(
    properties: Mapping[str, str],
    subject_id: str | None,
    test_user_ids: frozenset[str],
) -> dict[str, str]:
    """Override only the explicit typed-funnel test flag for configured internal users."""

    safe = dict(properties)
    if subject_id is not None and subject_id in test_user_ids and "test_traffic" in safe:
        safe["test_traffic"] = "true"
    return safe


def _repeat_activity_properties(
    entry_properties: Mapping[str, str],
    subject_id: str,
    first_entry_at: datetime,
    current_at: datetime,
) -> dict[str, str] | None:
    """Build one return event per local activity day, bucketed from the first entry."""

    timezone_name = entry_properties.get("calculation_timezone", "Europe/Moscow")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    first_day = first_entry_at.astimezone(timezone).date()
    current_day = current_at.astimezone(timezone).date()
    elapsed_days = (current_day - first_day).days
    if elapsed_days <= 0:
        return None
    if elapsed_days == 1:
        day_bucket = "d1"
    elif elapsed_days <= 6:
        day_bucket = "d2_6"
    elif elapsed_days <= 13:
        day_bucket = "d7_13"
    elif elapsed_days <= 29:
        day_bucket = "d14_29"
    else:
        day_bucket = "d30_plus"
    properties = dict(entry_properties)
    properties.update(
        {
            "entity_id": str(uuid5(_REPEAT_NAMESPACE, f"{subject_id}:{current_day.isoformat()}")),
            "activity_kind": "return",
            "day_bucket": day_bucket,
        }
    )
    return properties


def create_analytics_client(
    sessions: async_sessionmaker[AsyncSession], settings: ObservabilitySettings
) -> AnalyticsClient:
    """Compose one analytics provider for API and bot processes."""
    if settings.analytics_backend == "postgres":
        return ResilientAnalyticsClient(
            PostgresAnalyticsClient(sessions, settings.analytics_test_users)
        )
    return NoOpAnalyticsClient()
