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

logger = logging.getLogger(__name__)


async def _send_digest(
    bot: Bot,
    claim: DailyHoroscopeClaim,
    *,
    max_attempts: int,
    stopped: asyncio.Event,
) -> None:
    """Deliver one digest, waiting out the throttling Telegram reports explicitly.

    A 429 is the one failure that says for certain the message was *not* delivered, so it
    is the one failure worth retrying against the same claim. Everything else stays
    ambiguous and is left to the caller, which forfeits the day rather than risk sending
    the same digest twice. Retrying here is safe past the lease as well: the claim already
    reserved `last_delivered_on`, so no other worker can pick the row up for today.
    """

    for attempt in range(1, max_attempts + 1):
        try:
            await send_scene_photo(
                bot,
                claim.telegram_user_id,
                Scene.DAILY_HOROSCOPE,
                render_daily_horoscope(claim.delivery_date),
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
            try:
                await _send_digest(
                    bot,
                    claim,
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
