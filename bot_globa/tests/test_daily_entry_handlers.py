"""Contracts for the first on-demand daily horoscope entry."""

from app.bot import chat_scope_handlers
from app.bot.daily_entry_handlers import needs_daily_sign, router as daily_entry_router
from app.domain.daily_horoscope import DailyHoroscopeMode, DailyHoroscopePreferenceView
from app.domain.natal_chart import ZodiacSign


def _preference(sign: ZodiacSign | None) -> DailyHoroscopePreferenceView:
    return DailyHoroscopePreferenceView(
        mode=DailyHoroscopeMode.MORNING,
        timezone="Europe/Moscow",
        next_delivery_at=None,
        zodiac_sign=sign,
    )


def test_first_daily_entry_requires_sign_only_until_one_is_saved() -> None:
    assert needs_daily_sign(_preference(None)) is True
    assert needs_daily_sign(_preference(next(iter(ZodiacSign)))) is False


def test_daily_entry_router_runs_before_other_private_child_routes() -> None:
    assert chat_scope_handlers.router.sub_routers[0] is daily_entry_router
