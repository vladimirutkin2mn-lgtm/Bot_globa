"""Free daily sharing stays public-only and uses typed recipient attribution."""

from collections.abc import Mapping
from datetime import date
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from app.bot.daily_horoscope import render_compact_daily_horoscope, render_daily_horoscope
from app.bot.daily_keyboards import DAILY_SHARE_CALLBACK, daily_horoscope_with_sign_keyboard
from app.bot.public_share_handlers import (
    DAILY_SHARE_CAMPAIGN,
    DAILY_SHARE_ENTRY_PAYLOAD,
    DAILY_SHARE_FORMAT,
    DAILY_SHARE_SCENARIO,
    PERSONAL_SHARE_CAMPAIGN,
    _track_recipient_entry,
    _track_share_intent,
    build_daily_telegram_share_url,
    render_daily_public_share,
)
from app.domain.natal_chart import ZodiacSign
from app.providers.numa_product_analytics import ProductFlow, ProductFunnelEvent, ProductSource
from app.services.daily_horoscope_editorial import build_editorial_daily_horoscope
from app.services.numa_product_analytics import NumaProductAnalytics


class RecordingAnalytics:
    def __init__(self) -> None:
        self.events: list[tuple[str | None, str, dict[str, str]]] = []

    async def track(
        self,
        user_id: str | None,
        event: str,
        properties: Mapping[str, str] | None = None,
    ) -> None:
        self.events.append((user_id, event, dict(properties or {})))


def test_daily_keyboard_exposes_one_public_share_action() -> None:
    keyboard = daily_horoscope_with_sign_keyboard(ZodiacSign.ARIES)
    buttons = [button for row in keyboard.inline_keyboard for button in row]

    share = [button for button in buttons if button.callback_data == DAILY_SHARE_CALLBACK]
    assert len(share) == 1
    assert share[0].text == "📤 Поделиться темой дня"


def test_daily_public_share_drops_sign_specific_and_personal_content() -> None:
    snapshot = build_editorial_daily_horoscope(date(2026, 9, 11))
    all_signs = render_daily_horoscope(snapshot)
    aries = render_compact_daily_horoscope(snapshot, ZodiacSign.ARIES)

    shared_from_all = render_daily_public_share(all_signs)
    shared_from_sign = render_daily_public_share(aries)

    assert shared_from_all == shared_from_sign
    assert snapshot.theme in shared_from_all
    assert snapshot.signs[0].text not in shared_from_all
    assert "наталь" not in shared_from_all.casefold()
    assert "reading_id" not in shared_from_all
    assert shared_from_all.endswith("— Numa")


def test_daily_share_url_contains_only_aggregate_campaign_deeplink() -> None:
    snapshot = build_editorial_daily_horoscope(date(2026, 9, 11))
    source = render_daily_horoscope(snapshot)
    url = build_daily_telegram_share_url("@NumaTestBot", source)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "t.me"
    assert parsed.path == "/share/url"
    assert query["url"] == [f"https://t.me/NumaTestBot?start={DAILY_SHARE_ENTRY_PAYLOAD}"]
    assert query["text"] == [render_daily_public_share(source)]
    assert "user" not in url.casefold()
    assert "reading" not in url.casefold()


async def test_daily_share_intent_uses_daily_source_and_public_format() -> None:
    recording = RecordingAnalytics()
    analytics = NumaProductAnalytics(recording)
    user_id = uuid4()

    await _track_share_intent(analytics, user_id, "Гороскоп на сегодня\nТема дня\n— Numa")

    assert len(recording.events) == 1
    subject, event, properties = recording.events[0]
    assert subject == str(user_id)
    assert event == ProductFunnelEvent.SHARE_INTENT.value
    assert properties["flow"] == ProductFlow.DAILY.value
    assert properties["source"] == ProductSource.DAILY_HOROSCOPE.value
    assert properties["scenario_version"] == DAILY_SHARE_SCENARIO
    assert properties["share_format"] == DAILY_SHARE_FORMAT


async def test_recipient_entry_separates_daily_and_paid_share_sources() -> None:
    recording = RecordingAnalytics()
    analytics = NumaProductAnalytics(recording)
    user_id = uuid4()

    await _track_recipient_entry(
        analytics,
        user_id,
        flow=ProductFlow.DAILY,
        source=ProductSource.SHARED_DAILY,
        scenario_version=DAILY_SHARE_SCENARIO,
        campaign_code=DAILY_SHARE_CAMPAIGN,
    )
    await _track_recipient_entry(
        analytics,
        user_id,
        flow=ProductFlow.PERSONAL,
        source=ProductSource.SHARED_INSIGHT,
        scenario_version="personal_share_v2",
        campaign_code=PERSONAL_SHARE_CAMPAIGN,
    )

    assert [event for _, event, _ in recording.events] == [
        ProductFunnelEvent.RECIPIENT_ENTRY.value,
        ProductFunnelEvent.RECIPIENT_ENTRY.value,
    ]
    assert [properties["source"] for _, _, properties in recording.events] == [
        ProductSource.SHARED_DAILY.value,
        ProductSource.SHARED_INSIGHT.value,
    ]
    assert [properties["campaign_code"] for _, _, properties in recording.events] == [
        DAILY_SHARE_CAMPAIGN,
        PERSONAL_SHARE_CAMPAIGN,
    ]
