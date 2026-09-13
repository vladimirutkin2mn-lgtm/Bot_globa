"""Regression coverage for measurable daily-horoscope delivery and conversion."""

from collections.abc import Mapping
from datetime import date
from uuid import uuid4

from aiogram.types import CallbackQuery
from aiogram.types import User as TelegramUser

from app.bot.daily_keyboards import daily_horoscope_with_sign_keyboard, daily_personal_callback
from app.bot.numa_runtime_analytics import runtime_signal
from app.providers.numa_product_analytics import ProductFunnelEvent, ProductSource
from app.services.numa_daily_analytics import NumaDailyAnalytics, daily_episode_id
from app.services.numa_product_analytics import NumaProductAnalytics


class RecordingAnalytics:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, str, dict[str, str]]] = []

    async def track(
        self,
        user_id: str | None,
        event: str,
        properties: Mapping[str, str] | None = None,
    ) -> None:
        self.calls.append((user_id, event, dict(properties or {})))


async def test_daily_events_share_one_privacy_safe_episode() -> None:
    recording = RecordingAnalytics()
    analytics = NumaDailyAnalytics(NumaProductAnalytics(recording))
    user_id = uuid4()
    local_date = date(2026, 9, 13)

    await analytics.prepared(user_id, local_date, "Europe/Moscow")
    await analytics.delivered(user_id, local_date, "Europe/Moscow")
    await analytics.action(
        user_id,
        local_date,
        "Europe/Moscow",
        "personal_forecast_cta",
    )

    assert [event for _, event, _ in recording.calls] == [
        ProductFunnelEvent.DAILY_PREPARED.value,
        ProductFunnelEvent.DAILY_DELIVERED.value,
        ProductFunnelEvent.DAILY_ACTION.value,
    ]
    entity_ids = {properties["entity_id"] for _, _, properties in recording.calls}
    assert entity_ids == {str(daily_episode_id(user_id, local_date))}
    assert all(properties["flow"] == "daily" for _, _, properties in recording.calls)
    assert all(
        properties["source"] == ProductSource.DAILY_HOROSCOPE.value
        for _, _, properties in recording.calls
    )
    assert all(
        properties["scenario_version"] == "daily_horoscope_v1"
        for _, _, properties in recording.calls
    )
    assert recording.calls[1][2]["delivery_status"] == "telegram_accepted"
    assert recording.calls[2][2]["action_code"] == "personal_forecast_cta"
    assert all("telegram" not in key for _, _, properties in recording.calls for key in properties)


def test_daily_episode_is_stable_per_user_and_local_date() -> None:
    user_id = uuid4()
    first_day = date(2026, 9, 13)

    assert daily_episode_id(user_id, first_day) == daily_episode_id(user_id, first_day)
    assert daily_episode_id(user_id, first_day) != daily_episode_id(
        user_id,
        date(2026, 9, 14),
    )


def test_scheduled_keyboard_dates_personal_cta_but_legacy_default_stays_valid() -> None:
    delivery_date = date(2026, 9, 13)
    keyboard = daily_horoscope_with_sign_keyboard(None, delivery_date)
    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]

    assert daily_personal_callback() == "daily:personal"
    assert daily_personal_callback(delivery_date) == "daily:personal:2026-09-13"
    assert "daily:personal:2026-09-13" in callbacks


def test_dated_daily_cta_preserves_daily_acquisition_source() -> None:
    callback = CallbackQuery(
        id="daily-personal",
        from_user=TelegramUser(id=42, is_bot=False, first_name="Reader"),
        chat_instance="chat",
        data="daily:personal:2026-09-13",
    )

    signal = runtime_signal(callback)

    assert signal is not None
    assert signal.telegram_user_id == 42
    assert signal.attribution.source is ProductSource.DAILY_HOROSCOPE
    assert signal.attribution.scenario_version == "personal_day_forecast_v1"
