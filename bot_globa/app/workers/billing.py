"""Runnable payment jobs, reconciliation, subscription lifecycle, and outbox worker."""

import asyncio
import contextlib
import logging
import signal
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.bot.purchase_notifier import TelegramBuyerNotifier
from app.bot.typography import create_bot
from app.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.logging import configure_logging
from app.providers.analytics import DiscardingAnalyticsClient
from app.providers.payments.base import PaymentProviderName
from app.providers.payments.composition import create_payment_components
from app.providers.payments.telegram_stars import TELEGRAM_STARS_PROVIDER
from app.providers.payments.yookassa_gateway import YooKassaGateway
from app.providers.payments.yookassa_subscription_gateway import YooKassaSubscriptionGateway
from app.services.billing_job_worker import BillingJobWorker
from app.services.billing_outbox_service import BillingOutboxWorker
from app.services.checkout_service import ReceiptContactCipher
from app.services.payment_completion_service import PaymentCompletionService
from app.services.payment_reconciliation_service import PaymentReconciliationSweeper
from app.services.purchase_notification_service import PurchaseNotificationWorker
from app.services.refund_reconciliation_service import RefundReconciliationService
from app.services.subscription_event_processor import SubscriptionEventProcessor
from app.services.subscription_lifecycle import SubscriptionLifecycleService

logger = logging.getLogger(__name__)
_BILLING_WORKER_HEARTBEAT_PATH = Path("/app/.numa-billing-worker-heartbeat")


def _touch_billing_worker_heartbeat() -> None:
    """Record a completed worker loop without making the probe payment-critical."""

    try:
        _BILLING_WORKER_HEARTBEAT_PATH.touch()
    except OSError:
        logger.exception("billing_worker_heartbeat_failed")


def _clear_billing_worker_heartbeat() -> None:
    """Remove a stale probe from a previous process lifetime."""

    try:
        _BILLING_WORKER_HEARTBEAT_PATH.unlink(missing_ok=True)
    except OSError:
        logger.exception("billing_worker_heartbeat_reset_failed")


async def run(settings: Settings | None = None, stop: asyncio.Event | None = None) -> None:
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)
    engine = create_engine(str(resolved.database_url))
    sessions = create_session_factory(engine)
    # The bot is no longer only for Stars refunds: a hosted checkout completes here, and the
    # buyer only learns about it if this process can talk to Telegram.
    telegram_bot = create_bot(resolved.telegram_bot_token.get_secret_value())
    components = create_payment_components(resolved, telegram_bot)
    gateways = {name.value: gateway for name, gateway in components.gateways.items()}
    subscription_gateways = {
        name.value: gateway for name, gateway in components.subscription_gateways.items()
    }
    refund_gateways = {name.value: gateway for name, gateway in components.refund_gateways.items()}
    if resolved.yookassa_recurring_enabled:
        yookassa = components.subscription_gateways.get(PaymentProviderName.YOOKASSA)
        if not isinstance(yookassa, YooKassaGateway):
            raise ValueError("YooKassa recurring gateway is unavailable")
        subscription_gateways[PaymentProviderName.YOOKASSA.value] = YooKassaSubscriptionGateway(
            sessions, resolved, yookassa
        )
    completion = PaymentCompletionService(sessions, resolved.app_env == "production")
    lifecycle = SubscriptionLifecycleService(sessions)
    subscription_processor = SubscriptionEventProcessor(
        sessions, lifecycle, resolved.subscription_grace_period_days
    )
    refund_processor = RefundReconciliationService(
        sessions,
        resolved.billing_pending_reconciliation_seconds,
    )
    jobs = BillingJobWorker(
        sessions,
        gateways,
        completion,
        resolved.billing_worker_lease_seconds,
        resolved.billing_retry_base_seconds,
        resolved.billing_worker_max_attempts,
        resolved.payment_public_base_url,
        ReceiptContactCipher(resolved.content_encryption_key.get_secret_value()),
        subscription_gateways,
        subscription_processor,
        refund_gateways,
        refund_processor,
    )
    outbox = BillingOutboxWorker(
        sessions,
        DiscardingAnalyticsClient(),
        resolved.billing_worker_lease_seconds,
        resolved.billing_retry_base_seconds,
        resolved.billing_worker_max_attempts,
    )
    sweeper = PaymentReconciliationSweeper(
        sessions, resolved.billing_pending_reconciliation_seconds, set(gateways)
    )
    purchase_notifications = PurchaseNotificationWorker(
        sessions,
        TelegramBuyerNotifier(telegram_bot),
        resolved.reading_full_price_credits,
    )
    stopped = stop or asyncio.Event()
    worker_id = f"{socket.gethostname()}:{id(stopped)}"
    loop = asyncio.get_running_loop()
    if stop is None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stopped.set)
    next_sweep = datetime.now(UTC)
    _clear_billing_worker_heartbeat()
    try:
        while not stopped.is_set():
            now = datetime.now(UTC)
            if now >= next_sweep:
                await sweeper.enqueue_stale()
                if resolved.subscriptions_enabled:
                    await lifecycle.enqueue_due_renewals(
                        now=now,
                        exclude_providers={TELEGRAM_STARS_PROVIDER},
                    )
                    await lifecycle.finalize_terminal_states(
                        now=now,
                        grace_period=timedelta(days=resolved.subscription_grace_period_days),
                    )
                next_sweep = now + timedelta(
                    seconds=resolved.billing_reconciliation_interval_seconds
                )
            try:
                worked = await jobs.run_once(worker_id)
                worked = await outbox.run_once(worker_id) or worked
                worked = await purchase_notifications.run_once() or worked
                _touch_billing_worker_heartbeat()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("billing_worker_iteration_failed")
                worked = False
            if not worked:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stopped.wait(), timeout=1.0)
    finally:
        try:
            if telegram_bot is not None:
                await telegram_bot.session.close()
        finally:
            await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
