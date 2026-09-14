from urllib.parse import parse_qs, urlparse

from app.bot.public_share_handlers import (
    DAILY_SHARE_CONFIRM_CALLBACK,
    build_daily_telegram_share_url_from_public_text,
    daily_share_landing_keyboard,
    daily_share_preview_keyboard,
    extract_confirmed_daily_share,
    render_daily_public_share,
    render_daily_share_preview,
)
from app.bot.reading_feedback_handlers import feedback_recovery_keyboard


def _callbacks(keyboard) -> list[str]:
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def test_negative_feedback_recovery_has_concrete_next_steps() -> None:
    callbacks = _callbacks(feedback_recovery_keyboard())

    assert callbacks == ["menu:tarot", "menu:psychologist", "menu:astrologer"]
    assert all(len(value.encode("utf-8")) <= 64 for value in callbacks)


def test_daily_share_preview_round_trips_the_exact_public_text() -> None:
    source = (
        "Гороскоп на сегодня · 14 сентября\n\n"
        "🌙 Тема дня: не спешить с окончательным решением\n\n"
        "♈ Овен: личный текст, который не должен попасть в публичную карточку."
    )
    public_text = render_daily_public_share(source)
    preview = render_daily_share_preview(public_text)

    assert extract_confirmed_daily_share(preview) == public_text
    assert "личный текст" not in public_text
    assert public_text in preview


def test_daily_share_requires_explicit_confirmation_before_chat_picker() -> None:
    callbacks = _callbacks(daily_share_preview_keyboard())

    assert callbacks == [DAILY_SHARE_CONFIRM_CALLBACK, "menu:daily"]
    assert all(len(value.encode("utf-8")) <= 64 for value in callbacks)


def test_confirmed_daily_share_url_contains_only_confirmed_text_and_aggregate_referral() -> None:
    public_text = "Гороскоп на сегодня · 14 сентября\n🌙 Тема дня: держать фокус\n\n— Numa"

    url = build_daily_telegram_share_url_from_public_text("@numa_bot", public_text)
    query = parse_qs(urlparse(url).query)

    assert query["text"] == [public_text]
    assert query["url"] == ["https://t.me/numa_bot?start=share_day"]


def test_daily_share_recipient_goes_directly_to_daily_scenario() -> None:
    callbacks = _callbacks(daily_share_landing_keyboard())

    assert callbacks == ["menu:daily"]
