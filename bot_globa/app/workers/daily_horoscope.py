"""Graceful worker for default-on common daily-horoscope deliveries."""

import asyncio
import contextlib
import logging
import signal

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from app.bot.daily_horoscope import render_daily_horoscope
from app.bot.keyboards import daily_horoscope_keyboard
from app.bot.scene_media import Scene, send_scene_photo
from app.bot.typography import create_bot
from app.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.deployment import DeploymentSettings, get_deployment_settings
from app.domain.daily_horoscope import DailyHoroscopeClaim, DailyHoroscopeMode
from app.logging import configure_logging
from app.services.daily_horoscope import DailyHoroscopePreferenceService
from app.services.daily_horoscope_snapshot import DailyHoroscopeSnapshotService

logger = logging.getLogger(__name__)


async def _send_digest(
    bot: Bot,
    claim: DailyHoroscopeClaim,
    caption: str,
    *,
    max_attempts: int,
    stopped: asyncio.Event,
) -> None:
    """Deliver a prepared digest, waiting out explicit Telegram throttling.

    The caller reserves the local delivery day immediately before entering this function.
    From this point onward a non-429 failure is treated as ambiguous: Telegram may already
    have accepted the request, so the day stays reserved rather than risking a duplicate.
    """

    for attempt in range(1, max_attempts + 1):
        try:
            await send_scene_photo(
                bot,
                claim.telegram_user_id,
                Scene.DAILY_HOROSCOPE,
                caption,
                reply_markup=daily_horoscope_keyboard(),
            )
            return
        except TelegramRetryAfter as throttled:
            if attempt == max_attempts:
                raise
            logger.info(
                "daily_horoscope_throttled attempt=%s retry_after=%s",
                attempt,
                throttled.retry_after,
            )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stopped.wait(), timeout=throttled.retry_after)
            if stopped.is_set():
                raise


async def run(
    settings: Settings | None = None,
    deployment: DeploymentSettings | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Deliver every due local-morning schedule until SIGTERM/SIGINT."""

    resolved = settings or get_settings()
    runtime = deployment or get_deployment_settings()
    configure_logging(resolved.log_level)
    engine = create_engine(str(resolved.database_url))
    sessions = create_session_factory(engine)
    preferences = DailyHoroscopePreferenceService(sessions)
    snapshots = DailyHoroscopeSnapshotService(sessions)
    bot = create_bot(resolved.telegram_bot_token.get_secret_value())
    stopped = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    if stop is None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stopped.set)
    try:
        while not stopped.is_set():
            claim = await preferences.claim_due(lease_seconds=runtime.daily_horoscope_lease_seconds)
            if claim is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        stopped.wait(),
                        timeout=runtime.daily_horoscope_worker_idle_seconds,
                    )
                continue

            # Everything in this block is local preparation. A failure here is known to
            # have happened before any Telegram send attempt, so releasing the lease must
            # keep the same local day eligible for retry.
            try:
                snapshot = await snapshots.get_or_create(claim.delivery_date)
                caption = render_daily_horoscope(snapshot)
            except asyncio.CancelledError:
                await preferences.release(claim)
                raise
            except Exception:
                logger.exception("daily_horoscope_preparation_failed")
                await preferences.release(claim)
                continue

            # The at-most-once boundary is deliberately as late as possible: reserve the
            # local day only after content is ready, immediately before Telegram I/O.
            try:
                reserved = await preferences.reserve_send(claim)
                if not reserved:
                    await preferences.release(claim)
                    continue
                await _send_digest(
                    bot,
                    claim,
                    caption,
                    max_attempts=runtime.daily_horoscope_send_max_attempts,
                    stopped=stopped,
                )
            except asyncio.CancelledError:
                await preferences.release(claim)
                raise
            except TelegramForbiddenError:
                logger.info("daily_horoscope_recipient_unavailable")
                with contextlib.suppress(LookupError):
                    await preferences.configure(claim.user_id, DailyHoroscopeMode.DISABLED)
            except Exception:
                logger.exception("daily_horoscope_delivery_failed")
                await preferences.release(claim)
            else:
                await preferences.complete(claim)

            # Pace the broadcast: every active user shares one local 08:00, so without a
            # gap here the loop runs straight into Telegram's global rate limit and turns
            # a whole cohort's digest into retries.
            if runtime.daily_horoscope_send_interval_seconds:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        stopped.wait(),
                        timeout=runtime.daily_horoscope_send_interval_seconds,
                    )
    finally:
        try:
            await bot.session.close()
        finally:
            await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
