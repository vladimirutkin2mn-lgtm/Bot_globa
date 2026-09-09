"""Contracts for P0-03 user-facing names and promises."""

from app.bot import texts
from app.bot.keyboards import onboarding_intro_keyboard
from app.bot.reading_followup_handlers import SESSION_EXPIRED


def _callbacks() -> set[str]:
    keyboard = onboarding_intro_keyboard()
    return {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    }


def test_welcome_offers_useful_choices_without_intermediate_start() -> None:
    callbacks = _callbacks()

    assert "onboarding:intro" not in callbacks
    assert "oracle:auto" in callbacks
    assert "oracle:tarot" in callbacks
    assert "oracle:love" in callbacks
    assert "oracle:astro" in callbacks


def test_paid_reading_copy_matches_the_real_followup_entitlement() -> None:
    paywall = texts.PAYWALL.format(price="199 ₽")

    assert "до 3 уточняющих вопросов" in paywall
    assert "24 часов" in paywall
    assert "без доплаты" in paywall
    assert "«Моих историях»" in paywall


def test_followup_expiry_does_not_imply_the_purchased_result_disappears() -> None:
    assert "24 часа" in SESSION_EXPIRED
    assert "полный разбор остаётся доступен" in SESSION_EXPIRED
    assert "«Моих историях»" in SESSION_EXPIRED
