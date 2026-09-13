"""Privacy-safe analytics for one delivered Numa daily-horoscope episode."""

from collections.abc import Mapping
from datetime import date
from uuid import UUID, uuid5

from app.providers.numa_product_analytics import ProductFlow, ProductFunnelEvent, ProductSource
from app.services.numa_product_analytics import NumaProductAnalytics, ProductAttribution

_DAILY_NAMESPACE = UUID("fd618730-49c8-43d5-8ab7-2d1944776f25")
_DAILY_SCENARIO = "daily_horoscope_v1"


def daily_episode_id(user_id: UUID, local_date: date) -> UUID:
    """Return a stable opaque id for one user's local daily-horoscope episode."""

    return uuid5(_DAILY_NAMESPACE, f"{user_id}:{local_date.isoformat()}")


class NumaDailyAnalytics:
    """Emit typed daily events without Telegram ids or horoscope content."""

    def __init__(self, analytics: NumaProductAnalytics) -> None:
        self._analytics = analytics

    async def prepared(self, user_id: UUID, local_date: date, timezone: str) -> None:
        await self._track(
            user_id,
            local_date,
            timezone,
            ProductFunnelEvent.DAILY_PREPARED,
            {"local_date": local_date.isoformat()},
        )

    async def delivered(self, user_id: UUID, local_date: date, timezone: str) -> None:
        await self._track(
            user_id,
            local_date,
            timezone,
            ProductFunnelEvent.DAILY_DELIVERED,
            {
                "local_date": local_date.isoformat(),
                "delivery_status": "telegram_accepted",
            },
        )

    async def action(
        self,
        user_id: UUID,
        local_date: date,
        timezone: str,
        action_code: str,
    ) -> None:
        await self._track(
            user_id,
            local_date,
            timezone,
            ProductFunnelEvent.DAILY_ACTION,
            {"local_date": local_date.isoformat(), "action_code": action_code},
        )

    async def _track(
        self,
        user_id: UUID,
        local_date: date,
        timezone: str,
        event: ProductFunnelEvent,
        properties: Mapping[str, str],
    ) -> None:
        await self._analytics.track(
            user_id=user_id,
            entity_id=daily_episode_id(user_id, local_date),
            event=event,
            attribution=ProductAttribution(
                flow=ProductFlow.DAILY,
                source=ProductSource.DAILY_HOROSCOPE,
                scenario_version=_DAILY_SCENARIO,
                calculation_timezone=timezone,
            ),
            properties=properties,
        )
