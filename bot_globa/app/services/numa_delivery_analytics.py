"""Confirm free-answer delivery only after a Telegram handler returns successfully.

The store reads only operational Reading metadata and already validated analytics rows.
It never loads private question/result ciphertext or Telegram identifiers.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.analytics import AnalyticsEvent
from app.db.reading_models import Reading
from app.domain.reading import ReadingAccess, ReadingStatus
from app.observability.context import current_correlation_id
from app.providers.numa_product_analytics import ProductFlow, ProductFunnelEvent, ProductSource
from app.services.numa_product_analytics import NumaProductAnalytics, ProductAttribution


@dataclass(frozen=True, slots=True)
class FreeAnswerDeliveryCandidate:
    user_id: UUID
    reading_id: UUID
    attribution: ProductAttribution


class NumaDeliveryStore(Protocol):
    async def free_answer_candidate(
        self, correlation_id: str
    ) -> FreeAnswerDeliveryCandidate | None: ...


class SqlAlchemyNumaDeliveryStore:
    """Resolve the generated preview associated with the current Telegram update."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def free_answer_candidate(
        self, correlation_id: str
    ) -> FreeAnswerDeliveryCandidate | None:
        if correlation_id == "-":
            return None
        async with self._sessions() as session:
            event = await session.scalar(
                select(AnalyticsEvent)
                .where(
                    AnalyticsEvent.event_name == ProductFunnelEvent.FREE_ANSWER_READY.value,
                    AnalyticsEvent.correlation_id == correlation_id,
                )
                .order_by(AnalyticsEvent.created_at.desc())
                .limit(1)
            )
            if event is None or event.subject_id is None:
                return None
            try:
                user_id = UUID(event.subject_id)
                reading_id = UUID(event.properties["entity_id"])
                attribution = ProductAttribution(
                    flow=ProductFlow(event.properties["flow"]),
                    source=ProductSource(event.properties["source"]),
                    scenario_version=event.properties["scenario_version"],
                    experiment_assignment=event.properties["experiment_assignment"],
                    conversion_hook=event.properties["conversion_hook"],
                    test_traffic=event.properties["test_traffic"] == "true",
                    calculation_timezone=event.properties["calculation_timezone"],
                )
            except (KeyError, ValueError):
                return None
            reading = await session.get(Reading, reading_id)
            if (
                reading is None
                or reading.user_id != user_id
                or reading.status != ReadingStatus.PREVIEW_READY.value
                or reading.access_level != ReadingAccess.PREVIEW.value
            ):
                return None
            return FreeAnswerDeliveryCandidate(user_id, reading_id, attribution)


class NumaDeliveryAnalytics:
    """Record Telegram acceptance separately from generation readiness."""

    def __init__(self, store: NumaDeliveryStore, analytics: NumaProductAnalytics) -> None:
        self._store = store
        self._analytics = analytics

    async def confirm_current_free_answer(self) -> bool:
        candidate = await self._store.free_answer_candidate(current_correlation_id())
        if candidate is None:
            return False
        await self._analytics.track(
            user_id=candidate.user_id,
            entity_id=candidate.reading_id,
            event=ProductFunnelEvent.FREE_ANSWER_DELIVERED,
            attribution=candidate.attribution,
            properties={"delivery_status": "telegram_accepted"},
        )
        return True
