"""Privacy-safe analytics for paywall exposure and durable full unlocks."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.analytics import AnalyticsEvent
from app.db.reading_models import Reading
from app.domain.products import ProductCode
from app.providers.numa_product_analytics import (
    ProductFlow,
    ProductFunnelEvent,
    ProductSource,
    UnlockKind,
)
from app.services.numa_product_analytics import NumaProductAnalytics, ProductAttribution
from app.services.numa_reading_funnel_signal import (
    ReadingFunnelOutcome,
    consume_reading_funnel_signal,
)


@dataclass(frozen=True, slots=True)
class ReadingFunnelCandidate:
    user_id: UUID
    reading_id: UUID
    attribution: ProductAttribution


class NumaReadingFunnelStore(Protocol):
    async def candidate(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> ReadingFunnelCandidate | None: ...


class SqlAlchemyNumaReadingFunnelStore:
    """Recover funnel attribution without reading sensitive content."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def candidate(
        self,
        reading_id: UUID,
        user_id: UUID,
    ) -> ReadingFunnelCandidate | None:
        async with self._sessions() as session:
            reading = await session.get(Reading, reading_id)
            if reading is None or reading.user_id != user_id:
                return None

            events = (
                await session.scalars(
                    select(AnalyticsEvent)
                    .where(
                        AnalyticsEvent.event_name
                        == ProductFunnelEvent.FREE_ANSWER_READY.value,
                        AnalyticsEvent.subject_id == str(user_id),
                    )
                    .order_by(AnalyticsEvent.created_at.desc())
                    .limit(50)
                )
            ).all()
            event = next(
                (
                    item
                    for item in events
                    if item.properties.get("entity_id") == str(reading_id)
                ),
                None,
            )
            if event is None:
                return None
            try:
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
            return ReadingFunnelCandidate(user_id, reading_id, attribution)


class NumaReadingFunnelAnalytics:
    """Turn a request-local unlock outcome into one idempotent product event."""

    def __init__(
        self,
        store: NumaReadingFunnelStore,
        analytics: NumaProductAnalytics,
    ) -> None:
        self._store = store
        self._analytics = analytics

    async def confirm_current_outcome(self, *, handler_succeeded: bool) -> bool:
        signal = consume_reading_funnel_signal()
        if signal is None:
            return False
        if signal.outcome is ReadingFunnelOutcome.PAYWALL_REQUIRED and not handler_succeeded:
            return False

        candidate = await self._store.candidate(signal.reading_id, signal.user_id)
        if candidate is None:
            return False

        if signal.outcome is ReadingFunnelOutcome.PAYWALL_REQUIRED:
            event = ProductFunnelEvent.PAYWALL_SHOWN
            properties = None
        else:
            event = ProductFunnelEvent.FULL_UNLOCKED
            properties = {
                "unlock_kind": UnlockKind.EXISTING_CREDIT,
                "product_code": ProductCode.READING,
            }
        await self._analytics.track(
            user_id=candidate.user_id,
            entity_id=candidate.reading_id,
            event=event,
            attribution=candidate.attribution,
            properties=properties,
        )
        return True
