from datetime import date

from app.bot.public_share_handlers import (
    DAILY_SHARE_ENTRY_PAYLOAD,
    DAILY_SHARE_INLINE_CAPTION,
    build_daily_inline_result,
    build_daily_share_inline_query,
    daily_share_ready_keyboard,
    parse_daily_share_inline_query,
)
from app.bot.reading_feedback_handlers import router as reading_feedback_router
from app.services.daily_horoscope_editorial import build_editorial_daily_horoscope


def _public_text() -> str:
    return (
        "Гороскоп на сегодня · 15.09.2026\n"
        "🌙 Тема дня: не стоит форсировать то, что просит точной настройки.\n\n"
        "— Numa"
    )


def test_daily_inline_query_round_trips_forecast_date() -> None:
    inline_query = build_daily_share_inline_query(_public_text())

    assert inline_query == "daily-v5:2026-09-15"
    assert parse_daily_share_inline_query(inline_query) == date(2026, 9, 15)


def test_daily_inline_query_keeps_old_ready_buttons_working() -> None:
    assert parse_daily_share_inline_query("daily:2026-09-15") == date(2026, 9, 15)


def test_daily_inline_query_rejects_unknown_or_invalid_values() -> None:
    assert parse_daily_share_inline_query("other:2026-09-15") is None
    assert parse_daily_share_inline_query("daily-v5:not-a-date") is None


def test_daily_share_ready_keyboard_uses_chosen_chat_inline_picker() -> None:
    keyboard = daily_share_ready_keyboard(_public_text())
    share_button = keyboard.inline_keyboard[0][0]

    assert share_button.url is None
    assert share_button.switch_inline_query is None
    assert share_button.switch_inline_query_current_chat is None
    chooser = share_button.switch_inline_query_chosen_chat
    assert chooser is not None
    assert chooser.query == "daily-v5:2026-09-15"
    assert chooser.allow_user_chats is True
    assert chooser.allow_bot_chats is False
    assert chooser.allow_group_chats is True
    assert chooser.allow_channel_chats is True


def test_daily_inline_result_sends_actual_photo_with_numa_deeplink() -> None:
    forecast_date = date(2026, 9, 15)
    result = build_daily_inline_result(
        "@Numa_oracle_bot",
        "https://numa.example/",
        forecast_date,
    )
    expected_media = "https://numa.example/public/share/numa-daily-v5/2026-09-15.jpg"

    assert result.id == "daily-v5-2026-09-15"
    assert result.photo_url == expected_media
    assert result.thumbnail_url == expected_media
    assert result.photo_width == 1200
    assert result.photo_height == 1500
    assert result.caption == DAILY_SHARE_INLINE_CAPTION
    assert result.description == build_editorial_daily_horoscope(forecast_date).theme
    assert result.reply_markup is not None
    open_button = result.reply_markup.inline_keyboard[0][0]
    assert open_button.text == "✨ Открыть свой прогноз"
    assert open_button.url == (f"https://t.me/Numa_oracle_bot?start={DAILY_SHARE_ENTRY_PAYLOAD}")


def test_public_share_inline_handler_is_reachable_from_runtime_router_tree() -> None:
    assert "inline_query" in reading_feedback_router.resolve_used_update_types()
