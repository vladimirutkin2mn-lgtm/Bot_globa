from urllib.parse import parse_qs, urlsplit

from app.bot.public_share_handlers import build_daily_telegram_share_url_from_public_text


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


def test_daily_share_url_uses_public_visual_and_keeps_referral_in_text() -> None:
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
    assert query["url"] == ["https://numa.example/public/share/numa-daily-v1.jpg"]
    assert public_text in query["text"][0]
    assert "Остальное — в Numa ✨" in query["text"][0]
    assert deep_link in query["text"][0]
