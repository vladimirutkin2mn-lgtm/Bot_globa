from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest

from app.bot.public_share_handlers import (
    build_daily_share_media_url,
    build_daily_telegram_share_url_from_public_text,
    extract_daily_share_date,
)


def _public_text() -> str:
    return (
        "Гороскоп на сегодня · 15.09.2026\n"
        "🌙 Тема дня: не стоит форсировать то, что просит точной настройки.\n\n"
        "— Numa"
    )


def test_daily_share_url_uses_percent_encoding_for_spaces() -> None:
    public_text = _public_text()
    deep_link = "https://t.me/Numa_oracle_bot?start=share_day"

    share_url = build_daily_telegram_share_url_from_public_text(
        "Numa_oracle_bot",
        public_text,
    )
    query_string = urlsplit(share_url).query

    assert "+" not in query_string
    assert "%20" in query_string

    query = parse_qs(query_string)
    assert query["url"] == [deep_link]
    assert query["text"] == [public_text]


def test_daily_share_url_uses_date_specific_visual_and_keeps_referral_in_text() -> None:
    public_text = _public_text()
    deep_link = "https://t.me/Numa_oracle_bot?start=share_day"

    share_url = build_daily_telegram_share_url_from_public_text(
        "Numa_oracle_bot",
        public_text,
        public_base_url="https://numa.example/",
    )
    query_string = urlsplit(share_url).query
    query = parse_qs(query_string)

    assert "+" not in query_string
    assert query["url"] == ["https://numa.example/public/share/numa-daily-v5/2026-09-15.jpg"]
    assert public_text in query["text"][0]
    assert "Остальное — в Numa ✨" in query["text"][0]
    assert deep_link in query["text"][0]


def test_daily_share_media_url_changes_with_forecast_date() -> None:
    first = build_daily_share_media_url("https://numa.example", date(2026, 9, 15))
    second = build_daily_share_media_url("https://numa.example", date(2026, 9, 16))

    assert first == "https://numa.example/public/share/numa-daily-v5/2026-09-15.jpg"
    assert second == "https://numa.example/public/share/numa-daily-v5/2026-09-16.jpg"
    assert first != second


def test_daily_share_date_is_recovered_from_confirmed_public_copy() -> None:
    assert extract_daily_share_date(_public_text()) == date(2026, 9, 15)


@pytest.mark.parametrize(
    "public_text",
    [
        "🌙 Тема дня: настройка.",
        "Гороскоп на сегодня · nope\n🌙 Тема дня: настройка.",
        "Гороскоп на сегодня · 31.02.2026\n🌙 Тема дня: настройка.",
    ],
)
def test_daily_share_rejects_missing_or_invalid_forecast_date(public_text: str) -> None:
    with pytest.raises(ValueError, match="forecast date"):
        build_daily_telegram_share_url_from_public_text(
            "Numa_oracle_bot",
            public_text,
            public_base_url="https://numa.example",
        )
