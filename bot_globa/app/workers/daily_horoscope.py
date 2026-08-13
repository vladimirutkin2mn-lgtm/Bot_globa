"""Graceful worker for voluntary common daily-horoscope deliveries."""

import asyncio
import contextlib
import logging
import signal

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types.input_file import FSInputFile

from app.bot.daily_horoscope import render_daily_horoscope
from app.bot.keyboards import daily_horoscope_keyboard
from app.bot.scene_media import Scene
from app.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.deployment import DeploymentSettings, get_deployment_settings
from app.domain.daily_horoscope import DailyHoroscopeMode
from app.logging import configure_logging
from app.services.daily_horoscope import DailyHoroscopePreferenceService

logger = logging.getLogger(__name__)


async def run(
    settings: Settings | None = None,
    deployment: DeploymentSettings | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Deliver due opt-ins until SIGTERM/SIGINT."""

    resolved = settings or get_settings()
    runtime = deployment or get_deployment_settings()
    configure_logging(resolved.log_level)
    engine = create_engine(str(resolved.database_url))
    sessions = create_session_factory(engine)
    preferences = DailyHoroscopePreferenceService(sessions)
    bot = Bot(token=resolved.telegram_bot_token.get_secret_value())
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
                digest = render_daily_horoscope(claim.delivery_date)
                try:
                    await bot.send_photo(
                        chat_id=claim.telegram_user_id,
                        photo=FSInputFile(Scene.DAILY_HOROSCOPE.asset_path),
                        caption=digest,
                        reply_markup=daily_horoscope_keyboard(),
                    )
                except TelegramForbiddenError:
                    raise
                except TelegramAPIError:
                    logger.warning("daily_horoscope_photo_unavailable")
                    await bot.send_message(
                        chat_id=claim.telegram_user_id,
                        text=digest,
                        reply_markup=daily_horoscope_keyboard(),
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
    finally:
        try:
            await bot.session.close()
        finally:
            await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
