"""Per-update dependencies for the AI-oracle Telegram runtime."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.numa_runtime_analytics import runtime_entity_id, runtime_signal
from app.config import Settings
from app.domain.billing import BillingCatalog
from app.domain.products import ProductCatalog
from app.providers.analytics import AnalyticsClient
from app.providers.numa_product_analytics import ProductFunnelEvent
from app.providers.payments.base import PaymentProvider
from app.providers.payments.gateway import OneTimePaymentGateway
from app.repositories.users import SqlAlchemyUserRepository
from app.services.checkout_service import CheckoutService
from app.services.credits_service import CreditsService
from app.services.daily_horoscope import DailyHoroscopePreferenceService
from app.services.data_deletion import DataDeletionService
from app.services.numa_product_analytics import NumaProductAnalytics
from app.services.onboarding import OnboardingService
from app.services.oracle_memory_quality_service import QualityManagedOracleMemoryService
from app.services.payment_completion_service import PaymentCompletionService
from app.services.payment_service import PaymentService
from app.services.payment_status_service import PaymentStatusService
from app.services.preview_entitlement import PreviewEntitlementService
from app.services.refund_service import RefundService
from app.services.sensitive_content import AESGCMSensitiveContentCipher, decode_configured_key
from app.services.subscription_checkout_service import SubscriptionCheckoutService
from app.services.subscription_management_service import SubscriptionManagementService
from app.services.telegram_stars_service import TelegramStarsPaymentService

logger = logging.getLogger(__name__)


class OracleDependencyMiddleware(BaseMiddleware):
    """Inject only shared platform/oracle dependencies into active Telegram routes."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        analytics: AnalyticsClient,
        settings: Settings,
        payment_provider: PaymentProvider | None,
        product_catalog: ProductCatalog,
        checkout_service: CheckoutService,
        subscription_checkout: SubscriptionCheckoutService | None = None,
        subscriptions: SubscriptionManagementService | None = None,
        refunds: RefundService | None = None,
        telegram_stars: TelegramStarsPaymentService | None = None,
        payment_gateways: dict[str, OneTimePaymentGateway] | None = None,
        payment_completion: PaymentCompletionService | None = None,
    ) -> None:
        self._sessions = sessions
        self._analytics = analytics
        self._numa_product_analytics = NumaProductAnalytics(analytics)
        self._settings = settings
        self._payment_provider = payment_provider
        self._product_catalog = product_catalog
        self._billing_catalog = BillingCatalog(settings)
        self._checkout_service = checkout_service
        self._subscription_checkout = subscription_checkout
        self._subscriptions = subscriptions
        self._refunds = refunds
        self._telegram_stars = telegram_stars
        self._payment_gateways = payment_gateways or {}
        self._payment_completion = payment_completion

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self._sessions() as session:
            cipher = AESGCMSensitiveContentCipher(
                decode_configured_key(self._settings.content_encryption_key.get_secret_value())
            )
            daily_horoscopes = DailyHoroscopePreferenceService(self._sessions)
            onboarding = OnboardingService(
                SqlAlchemyUserRepository(session), self._analytics, daily_horoscopes
            )
            data["onboarding"] = onboarding
            data["oracle_memory"] = QualityManagedOracleMemoryService(self._sessions, cipher)
            data["credits"] = CreditsService(self._sessions)
            data["previews"] = PreviewEntitlementService(self._sessions)
            data["catalog"] = self._product_catalog
            data["billing_catalog"] = self._billing_catalog
            data["payments"] = (
                PaymentService(
                    self._sessions,
                    self._product_catalog,
                    self._payment_provider,
                    self._analytics,
                    self._settings.payment_provider,
                    self._settings.checkout_creation_lease_seconds,
                )
                if self._payment_provider is not None
                else None
            )
            data["checkout"] = self._checkout_service
            data["payment_status"] = PaymentStatusService(
                self._sessions,
                self._settings.billing_pending_reconciliation_seconds,
                self._payment_gateways,
                self._payment_completion,
            )
            data["subscription_checkout"] = self._subscription_checkout
            data["subscriptions"] = self._subscriptions
            data["refunds"] = self._refunds
            data["telegram_stars"] = self._telegram_stars
            data["billing_settings"] = self._settings
            data["analysis_price"] = self._settings.reading_full_price_credits
            data["analytics"] = self._analytics
            data["numa_product_analytics"] = self._numa_product_analytics
            data["data_deletion"] = DataDeletionService(session, self._analytics)
            data["daily_horoscopes"] = daily_horoscopes
            data["privacy_retention_days"] = self._settings.raw_content_retention_days
            result = await handler(event, data)
            await self._track_runtime_signal(event, onboarding)
            return result

    async def _track_runtime_signal(
        self,
        event: TelegramObject,
        onboarding: OnboardingService,
    ) -> None:
        signal = runtime_signal(event)
        if signal is None:
            return
        internal_user_id = None
        if signal.telegram_user_id is not None:
            user = await onboarding.current_user(signal.telegram_user_id)
            if user is not None:
                internal_user_id = user.id
        try:
            await self._numa_product_analytics.track(
                user_id=internal_user_id,
                entity_id=runtime_entity_id(signal, internal_user_id),
                event=ProductFunnelEvent.ENTRY,
                attribution=signal.attribution,
            )
        except Exception:
            logger.warning(
                "numa_runtime_analytics_failed source=%s",
                signal.attribution.source.value,
            )
