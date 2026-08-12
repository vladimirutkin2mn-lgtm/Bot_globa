"""User-owned subscription query, cancel and resume operations."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import Subscription, User
from app.providers.payments.subscription_gateway import (
    SubscriptionGateway,
    SubscriptionStateFact,
)
from app.providers.payments.telegram_stars import (
    TELEGRAM_STARS_PROVIDER,
    TelegramStarsSubscriptionControl,
)
from app.services.subscription_event_processor import SubscriptionEventProcessor

_ACTIVE = ("incomplete", "active", "past_due", "cancel_at_period_end", "paused")


class SubscriptionManagementOutcome(StrEnum):
    UPDATED = "updated"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    ALREADY_SET = "already_set"


@dataclass(frozen=True)
class SubscriptionView:
    id: UUID
    provider: str
    product_code: str
    status: str
    current_period_end: datetime | None


class SubscriptionManagementService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: Settings,
        gateways: dict[str, SubscriptionGateway],
        processor: SubscriptionEventProcessor,
        telegram_stars: TelegramStarsSubscriptionControl | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._gateways = gateways
        self._processor = processor
        self._telegram_stars = telegram_stars

    async def current(self, user_id: UUID) -> SubscriptionView | None:
        async with self._sessions() as session:
            value = await session.scalar(
                select(Subscription)
                .where(Subscription.user_id == user_id, Subscription.status.in_(_ACTIVE))
                .order_by(Subscription.created_at.desc())
            )
            return None if value is None else self._view(value)

    async def cancel(self, user_id: UUID, subscription_id: UUID) -> SubscriptionManagementOutcome:
        owned = await self._owned(user_id, subscription_id)
        if owned is None:
            return SubscriptionManagementOutcome.NOT_FOUND
        subscription, telegram_user_id = owned
        if subscription.status == "cancel_at_period_end":
            return SubscriptionManagementOutcome.ALREADY_SET
        if not self._settings.permits_renewal():
            return SubscriptionManagementOutcome.UNAVAILABLE
        if subscription.provider == "yookassa":
            return await self._apply_local_yookassa(subscription, cancel_at_period_end=True)
        if subscription.provider == TELEGRAM_STARS_PROVIDER:
            if telegram_user_id is None:
                return SubscriptionManagementOutcome.UNAVAILABLE
            return await self._apply_telegram_stars(
                subscription,
                telegram_user_id,
                cancel_at_period_end=True,
            )
        gateway = self._gateways.get(subscription.provider)
        if gateway is None:
            return SubscriptionManagementOutcome.UNAVAILABLE
        fact = await gateway.cancel_subscription(subscription.provider_subscription_id)
        await self._processor.apply(fact)
        return SubscriptionManagementOutcome.UPDATED

    async def resume(self, user_id: UUID, subscription_id: UUID) -> SubscriptionManagementOutcome:
        owned = await self._owned(user_id, subscription_id)
        if owned is None:
            return SubscriptionManagementOutcome.NOT_FOUND
        subscription, telegram_user_id = owned
        if subscription.status != "cancel_at_period_end":
            return SubscriptionManagementOutcome.ALREADY_SET
        if not self._settings.permits_renewal():
            return SubscriptionManagementOutcome.UNAVAILABLE
        if subscription.provider == "yookassa":
            return await self._apply_local_yookassa(subscription, cancel_at_period_end=False)
        if subscription.provider == TELEGRAM_STARS_PROVIDER:
            if telegram_user_id is None:
                return SubscriptionManagementOutcome.UNAVAILABLE
            return await self._apply_telegram_stars(
                subscription,
                telegram_user_id,
                cancel_at_period_end=False,
            )
        gateway = self._gateways.get(subscription.provider)
        if gateway is None:
            return SubscriptionManagementOutcome.UNAVAILABLE
        fact = await gateway.resume_subscription(subscription.provider_subscription_id)
        await self._processor.apply(fact)
        return SubscriptionManagementOutcome.UPDATED

    async def _apply_local_yookassa(
        self, subscription: Subscription, *, cancel_at_period_end: bool
    ) -> SubscriptionManagementOutcome:
        if not self._settings.yookassa_recurring_enabled:
            return SubscriptionManagementOutcome.UNAVAILABLE
        if subscription.current_period_end is None:
            return SubscriptionManagementOutcome.UNAVAILABLE
        await self._processor.apply(
            SubscriptionStateFact(
                user_id=subscription.user_id,
                provider="yookassa",
                provider_subscription_id=subscription.provider_subscription_id,
                status="active",
                current_period_start=subscription.current_period_start,
                current_period_end=subscription.current_period_end,
                cancel_at_period_end=cancel_at_period_end,
            )
        )
        return SubscriptionManagementOutcome.UPDATED

    async def _apply_telegram_stars(
        self,
        subscription: Subscription,
        telegram_user_id: int,
        *,
        cancel_at_period_end: bool,
    ) -> SubscriptionManagementOutcome:
        if self._telegram_stars is None or subscription.current_period_end is None:
            return SubscriptionManagementOutcome.UNAVAILABLE
        await self._telegram_stars.set_subscription_canceled(
            telegram_user_id,
            subscription.provider_subscription_id,
            is_canceled=cancel_at_period_end,
        )
        await self._processor.apply(
            SubscriptionStateFact(
                user_id=subscription.user_id,
                provider=TELEGRAM_STARS_PROVIDER,
                provider_subscription_id=subscription.provider_subscription_id,
                status="active",
                current_period_start=subscription.current_period_start,
                current_period_end=subscription.current_period_end,
                cancel_at_period_end=cancel_at_period_end,
            )
        )
        return SubscriptionManagementOutcome.UPDATED

    async def _owned(
        self, user_id: UUID, subscription_id: UUID
    ) -> tuple[Subscription, int | None] | None:
        async with self._sessions() as session:
            user = await session.get(User, user_id)
            if user is None or user.privacy_status != "active":
                return None
            value: Subscription | None = await session.scalar(
                select(Subscription).where(
                    Subscription.id == subscription_id,
                    Subscription.user_id == user_id,
                    Subscription.status.in_(_ACTIVE),
                )
            )
            return None if value is None else (value, user.telegram_user_id)

    @staticmethod
    def _view(value: Subscription) -> SubscriptionView:
        return SubscriptionView(
            id=value.id,
            provider=value.provider,
            product_code=value.product_code,
            status=value.status,
            current_period_end=value.current_period_end,
        )
