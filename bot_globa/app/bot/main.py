"""aiogram bootstrap for local long-polling and shared dispatcher construction."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncEngine

from app.bot.commands import configure_commands
from app.bot.core_handlers import router as core_router
from app.bot.daily_conversion_handlers import router as daily_conversion_router
from app.bot.daily_feedback_handlers import router as daily_feedback_router
from app.bot.group_handlers import router as group_router
from app.bot.horoscope_handlers import create_horoscope_router
from app.bot.horoscope_renderer import HoroscopeRenderer
from app.bot.memory_handlers import router as memory_router
from app.bot.observability import TelegramObservabilityMiddleware
from app.bot.oracle_dependencies import OracleDependencyMiddleware
from app.bot.persona_flow import PersonaReadingBundle
from app.bot.persona_flows import MVP_READING_FLOWS, TAROT_FLOW
from app.bot.persona_handlers import create_persona_router
from app.bot.personal_oracle_handlers import router as personal_oracle_router
from app.bot.postgres_fsm import PostgresEventIsolation, PostgresFSMStorage
from app.bot.pricing import product_price_label
from app.bot.rate_limit import FixedWindowRateLimiter, RateLimitMiddleware
from app.bot.reading_feedback_handlers import router as reading_feedback_router
from app.bot.reading_followup_handlers import create_reading_followup_router
from app.bot.reading_safety_middleware import ReadingSafetyHandoffMiddleware
from app.bot.refund_handlers import router as refund_router
from app.bot.subscription_handlers import router as subscription_router
from app.bot.telegram_stars_handlers import router as telegram_stars_router
from app.bot.typography import create_bot
from app.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.domain.billing import BillingCatalog
from app.domain.products import ProductCatalog, ProductCode
from app.logging import configure_logging
from app.observability.errors import LoggingErrorReporter, NoOpErrorReporter
from app.observability.langsmith import wrap_llm_with_langsmith
from app.observability.oracle_quality import (
    LLMCostPolicy,
    ObservedLLMClient,
    OracleQualityObserver,
)
from app.observability.settings import ObservabilitySettings, get_observability_settings
from app.providers.analytics_postgres import create_analytics_client
from app.providers.geocoding.base import close_geocoding_client
from app.providers.geocoding.factory import create_geocoding_client
from app.providers.llm.base import close_llm_client
from app.providers.llm.factory import create_llm_client
from app.providers.payments.composition import create_payment_components
from app.release_settings import OracleReleaseSettings, get_oracle_release_settings
from app.repositories.reading_generation import SqlAlchemyReadingGenerationStore
from app.services.birth_place_lookup import BirthPlaceLookupService
from app.services.birth_profile import BirthProfileService
from app.services.checkout_service import CheckoutService
from app.services.credits_service import CreditsService
from app.services.horoscope_facts import HoroscopeFactService
from app.services.horoscope_generation import HoroscopeGenerationService
from app.services.horoscope_reading import HoroscopeReadingUseCase
from app.services.monetized_reading import MonetizedReadingService
from app.services.natal_chart import (
    AstronomyEngineNatalChartCalculator,
    ConsentedNatalChartService,
)
from app.services.oracle_memory_quality_service import QualityManagedOracleMemoryService
from app.services.oracle_product_analytics import OracleProductAnalytics
from app.services.oracle_release_controls import OracleReleaseControls
from app.services.payment_completion_service import PaymentCompletionService
from app.services.persona_reading import PersonaReadingUseCase, SymbolDrawer
from app.services.persona_registry import PersonaRegistryService
from app.services.preview_entitlement import PreviewEntitlementService
from app.services.reading_followup import ReadingFollowUpService
from app.services.reading_generation import ReadingGenerationService
from app.services.reading_history import ReadingHistoryService
from app.services.reading_memory_context import OracleReadingMemoryRetriever
from app.services.reading_service import ReadingService
from app.services.refund_service import RefundService
from app.services.sensitive_content import AESGCMSensitiveContentCipher, decode_configured_key
from app.services.subscription_checkout_service import SubscriptionCheckoutService
from app.services.subscription_event_processor import SubscriptionEventProcessor
from app.services.subscription_lifecycle import SubscriptionLifecycleService
from app.services.subscription_management_service import SubscriptionManagementService
from app.services.symbolic_engine import TarotSymbolDrawer
from app.services.telegram_stars_service import TelegramStarsPaymentService

logger = logging.getLogger(__name__)


async def prepare_runtime(bot: Bot, persona_registry: PersonaRegistryService) -> None:
    """Do everything that must happen once before this process serves an update.

    Deliberately explicit rather than registered on `dispatcher.startup`: production does
    not poll. `app.workers.telegram` feeds updates straight into the dispatcher and never
    emits aiogram's startup event, so a hook registered there runs locally, looks correct
    in review, and silently never runs on the server. Personas are the case that matters —
    without their rows `enabled_persona` finds nothing and every reading fails with
    `PersonaUnavailableError`.

    Both steps are idempotent, so every replica may run them at boot.
    """

    await persona_registry.sync_mvp_personas()
    await configure_commands(bot)


def create_dispatcher(
    settings: Settings,
    observability_settings: ObservabilitySettings | None = None,
    engine: AsyncEngine | None = None,
    release_settings: OracleReleaseSettings | None = None,
    bot: Bot | None = None,
) -> Dispatcher:
    """Create the Oracle-only dispatcher over reusable platform infrastructure."""

    resolved_observability = observability_settings or get_observability_settings()
    resolved_release = release_settings or get_oracle_release_settings()
    resolved_engine = engine or create_engine(str(settings.database_url))
    sessions = create_session_factory(resolved_engine)
    release_controls = OracleReleaseControls.from_settings(resolved_release)
    cipher = AESGCMSensitiveContentCipher(
        decode_configured_key(settings.content_encryption_key.get_secret_value())
    )
    dispatcher = Dispatcher(
        storage=PostgresFSMStorage(sessions, cipher),
        events_isolation=PostgresEventIsolation(resolved_engine),
    )
    raw_llm = create_llm_client(settings)
    traced_llm = wrap_llm_with_langsmith(raw_llm, resolved_observability)
    payments = create_payment_components(settings, bot)
    product_catalog = ProductCatalog(settings)
    billing_catalog = BillingCatalog(settings)
    reading_full_price_label = product_price_label(
        billing_catalog,
        ProductCode.READING_SINGLE,
        settings,
    )
    analytics = create_analytics_client(sessions, resolved_observability)
    oracle_analytics = OracleProductAnalytics(analytics)
    quality_observer = OracleQualityObserver(
        analytics,
        default_provider=settings.llm_provider,
        default_model=settings.llm_model,
        cost_policy=LLMCostPolicy(
            settings.llm_model,
            resolved_observability.llm_input_cost_usd_per_million_tokens,
            resolved_observability.llm_output_cost_usd_per_million_tokens,
        ),
    )
    llm = ObservedLLMClient(traced_llm, quality_observer)
    reporter = (
        LoggingErrorReporter()
        if resolved_observability.error_reporting_backend == "logging"
        else NoOpErrorReporter()
    )
    lifecycle = SubscriptionLifecycleService(sessions)
    processor = SubscriptionEventProcessor(
        sessions, lifecycle, settings.subscription_grace_period_days
    )
    payment_completion = PaymentCompletionService(sessions, settings.app_env == "production")
    telegram_stars = TelegramStarsPaymentService(
        sessions,
        settings,
        billing_catalog,
        payment_completion,
        processor,
    )
    one_time_gateways = {name.value: gateway for name, gateway in payments.gateways.items()}
    subscription_gateways = {
        name.value: gateway for name, gateway in payments.subscription_gateways.items()
    }
    refund_gateways = {name.value: gateway for name, gateway in payments.refund_gateways.items()}
    dependency_middleware = OracleDependencyMiddleware(
        sessions,
        analytics,
        settings,
        payments.legacy,
        product_catalog,
        CheckoutService(sessions, settings, billing_catalog, payments.gateways),
        SubscriptionCheckoutService(
            sessions, settings, billing_catalog, payments.subscription_gateways
        ),
        SubscriptionManagementService(
            sessions,
            settings,
            subscription_gateways,
            processor,
            payments.telegram_stars,
        ),
        RefundService(sessions, settings, refund_gateways),
        telegram_stars,
        payment_gateways=one_time_gateways,
        payment_completion=payment_completion,
    )
    rate_middleware = RateLimitMiddleware(FixedWindowRateLimiter())
    safety_middleware = ReadingSafetyHandoffMiddleware()
    dispatcher.message.outer_middleware(rate_middleware)
    dispatcher.callback_query.outer_middleware(rate_middleware)
    dispatcher.message.outer_middleware(safety_middleware)
    dispatcher.callback_query.outer_middleware(safety_middleware)
    dispatcher.update.outer_middleware(TelegramObservabilityMiddleware(reporter))
    dispatcher.update.outer_middleware(dependency_middleware)

    dispatcher.include_router(telegram_stars_router)
    dispatcher.include_router(refund_router)
    dispatcher.include_router(subscription_router)
    dispatcher.include_router(memory_router)
    dispatcher.include_router(personal_oracle_router)
    for flow in MVP_READING_FLOWS:
        dispatcher.include_router(create_persona_router(flow))
    dispatcher.include_router(daily_conversion_router)
    dispatcher.include_router(daily_feedback_router)
    dispatcher.include_router(create_horoscope_router())
    dispatcher.include_router(reading_feedback_router)
    dispatcher.include_router(create_reading_followup_router())
    dispatcher.include_router(group_router)
    dispatcher.include_router(core_router)
    dispatcher["database_engine"] = resolved_engine
    dispatcher["owns_database_engine"] = engine is None
    dispatcher["llm_client"] = llm
    dispatcher["analytics"] = analytics
    dispatcher["oracle_analytics"] = oracle_analytics
    dispatcher["oracle_quality_observer"] = quality_observer
    dispatcher["oracle_release_controls"] = release_controls
    dispatcher["error_reporter"] = reporter
    dispatcher["persona_registry"] = PersonaRegistryService(sessions)
    dispatcher["reading_history"] = ReadingHistoryService(sessions)
    preview_entitlements = PreviewEntitlementService(sessions)
    reading_service = ReadingService(
        sessions,
        cipher,
        settings.raw_content_retention_days,
        preview_entitlements=preview_entitlements,
        analytics=oracle_analytics,
        release_controls=release_controls,
    )
    dispatcher["reading_service"] = reading_service
    oracle_memory = QualityManagedOracleMemoryService(sessions, cipher)
    reading_store = SqlAlchemyReadingGenerationStore(
        sessions,
        cipher,
        settings.raw_content_retention_days,
    )
    reading_generation = ReadingGenerationService(
        reading_store,
        llm,
        max_repair_attempts=settings.llm_max_repair_attempts,
        memory_retriever=OracleReadingMemoryRetriever(oracle_memory),
        analytics=oracle_analytics,
        quality_observer=quality_observer,
    )
    monetized_readings = MonetizedReadingService(
        sessions,
        CreditsService(sessions),
        reading_service,
        settings.reading_full_price_credits,
    )
    # Only the tarot persona has a deterministic symbol set; the others reason in words.
    drawers: dict[str, SymbolDrawer] = {TAROT_FLOW.persona_code: TarotSymbolDrawer()}
    dispatcher["persona_readings"] = {
        flow.persona_code: PersonaReadingBundle(
            use_case=PersonaReadingUseCase.from_services(
                flow.persona_code,
                reading_service,
                reading_generation,
                drawer=drawers.get(flow.persona_code),
                entitlements=preview_entitlements,
            ),
            monetized=monetized_readings,
            full_price_label=reading_full_price_label,
            memory=oracle_memory,
        )
        for flow in MVP_READING_FLOWS
    }
    birth_profiles = BirthProfileService(sessions, cipher, analytics=oracle_analytics)
    natal_charts = ConsentedNatalChartService(
        birth_profiles,
        AstronomyEngineNatalChartCalculator(),
    )
    horoscope_facts = HoroscopeFactService(natal_charts)
    geocoder = create_geocoding_client(settings)
    dispatcher["geocoding_client"] = geocoder
    dispatcher["birth_profile_service"] = birth_profiles
    dispatcher["birth_place_lookup"] = BirthPlaceLookupService(geocoder)
    dispatcher["horoscope_use_case"] = HoroscopeReadingUseCase.from_services(
        reading_service,
        HoroscopeGenerationService(
            reading_store,
            llm,
            horoscope_facts,
            max_repair_attempts=settings.llm_max_repair_attempts,
            analytics=oracle_analytics,
            quality_observer=quality_observer,
        ),
        entitlements=preview_entitlements,
    )
    dispatcher["horoscope_renderer"] = HoroscopeRenderer()
    dispatcher["horoscope_monetized"] = monetized_readings
    dispatcher["reading_full_price_label"] = reading_full_price_label
    dispatcher["reading_followups"] = ReadingFollowUpService(
        sessions,
        cipher,
        llm,
        analytics,
        settings.llm_provider,
        settings.llm_model,
        max_repair_attempts=settings.llm_max_repair_attempts,
    )
    return dispatcher


async def close_dispatcher(dispatcher: Dispatcher) -> None:
    """Close provider/FSM resources and only engines owned by this dispatcher."""
    try:
        await close_llm_client(dispatcher["llm_client"])
    except Exception:
        logger.warning("LLM client shutdown failed")
    try:
        await close_geocoding_client(dispatcher["geocoding_client"])
    except Exception:
        logger.warning("Geocoding client shutdown failed")
    await dispatcher.fsm.close()
    if dispatcher["owns_database_engine"]:
        await dispatcher["database_engine"].dispose()


async def configure_webhook(bot: Bot, settings: Settings) -> None:
    """Register webhook delivery using Telegram's verification secret."""
    await bot.set_webhook(
        url=settings.telegram_webhook_url,
        secret_token=settings.telegram_webhook_secret.get_secret_value(),
        allowed_updates=["message", "callback_query", "pre_checkout_query", "subscription"],
    )


async def run(settings: Settings | None = None) -> None:
    """Run local polling; production webhook updates belong to the durable worker."""
    resolved_settings = settings or get_settings()
    if resolved_settings.webhook_enabled:
        raise ValueError("webhook mode requires app.workers.telegram")
    configure_logging(resolved_settings.log_level)
    bot = create_bot(resolved_settings.telegram_bot_token.get_secret_value())
    dispatcher = create_dispatcher(resolved_settings, bot=bot)
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await prepare_runtime(bot, dispatcher["persona_registry"])
        await dispatcher.start_polling(bot)
    finally:
        try:
            await close_dispatcher(dispatcher)
        finally:
            await bot.session.close()


def main() -> None:
    """Synchronous console entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
