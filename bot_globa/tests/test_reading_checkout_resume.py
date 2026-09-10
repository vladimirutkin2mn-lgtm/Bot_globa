"""Pure contracts for durable hosted-checkout reading resume targets."""

from uuid import uuid4

from aiogram.types import InlineKeyboardMarkup

from app.bot.purchase_notifier import purchase_received_keyboard
from app.domain.reading_checkout_resume import (
    ReadingCheckoutTarget,
    parse_reading_resume_callback,
    reading_target_from_snapshot,
)


def _callback(keyboard: InlineKeyboardMarkup) -> str | None:
    return keyboard.inline_keyboard[0][0].callback_data


def test_known_reading_callback_round_trips_through_snapshot() -> None:
    reading_id = uuid4()
    target = parse_reading_resume_callback(f"love:unlock:{reading_id}")

    assert target == ReadingCheckoutTarget(reading_id, "love_oracle")
    assert target is not None
    assert reading_target_from_snapshot({"resume_target": target.snapshot()}) == target
    assert target.callback_data == f"love:unlock:{reading_id}"


def test_unknown_or_malformed_callback_is_never_persisted_as_a_target() -> None:
    reading_id = uuid4()

    assert parse_reading_resume_callback(f"admin:unlock:{reading_id}") is None
    assert parse_reading_resume_callback("tarot:unlock:not-a-uuid") is None
    assert parse_reading_resume_callback(f"tarot:history:{reading_id}") is None
    assert reading_target_from_snapshot({"resume_target": {"kind": "reading"}}) is None


def test_purchase_notice_uses_exact_reading_only_for_validated_callback_shape() -> None:
    reading_id = uuid4()

    assert _callback(purchase_received_keyboard(f"astro:unlock:{reading_id}")) == (
        f"astro:unlock:{reading_id}"
    )
    assert _callback(purchase_received_keyboard("evil:unlock:payload")) == "credits:refresh"
    assert _callback(purchase_received_keyboard()) == "credits:refresh"
