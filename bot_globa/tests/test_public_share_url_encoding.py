from urllib.parse import parse_qs, urlsplit

from app.bot.public_share_handlers import build_daily_telegram_share_url_from_public_text


def test_daily_share_url_uses_percent_encoding_for_spaces() -> None:
    public_text = (
        "Гороскоп на сегодня · 15.09.2026\n"
        "🌙 Тема дня: не стоит форсировать то, что просит точной настройки.\n\n"
        "— Numa"
    )
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
