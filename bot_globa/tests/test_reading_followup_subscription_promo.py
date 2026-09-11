"""A completed paid-session follow-up is a privacy-safe repeat meaningful-usage signal."""

from uuid import uuid4

from app.bot.reading_followup_handlers import (
    SUBSCRIPTION_PROMO_BUTTON,
    SUBSCRIPTION_PROMO_CALLBACK,
    _followup_result_keyboard,
)


def _buttons(*, subscriptions_enabled: bool, remaining: int = 2) -> list[tuple[str, str | None]]:
    keyboard = _followup_result_keyboard(
        uuid4(),
        remaining,
        subscriptions_enabled=subscriptions_enabled,
    )
    return [
        (button.text, button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
    ]


def test_followup_promotes_subscription_when_subscriptions_are_enabled() -> None:
    buttons = _buttons(subscriptions_enabled=True)

    assert (SUBSCRIPTION_PROMO_BUTTON, SUBSCRIPTION_PROMO_CALLBACK) in buttons
    assert buttons[0][0].startswith("Ещё вопрос")
    assert buttons[-1][1] == "report:menu"


def test_followup_hides_subscription_promo_when_subscriptions_are_disabled() -> None:
    buttons = _buttons(subscriptions_enabled=False)

    assert (SUBSCRIPTION_PROMO_BUTTON, SUBSCRIPTION_PROMO_CALLBACK) not in buttons


def test_subscription_promo_remains_after_included_followups_are_exhausted() -> None:
    buttons = _buttons(subscriptions_enabled=True, remaining=0)

    assert buttons[0] == (SUBSCRIPTION_PROMO_BUTTON, SUBSCRIPTION_PROMO_CALLBACK)
    assert all(not text.startswith("Ещё вопрос") for text, _ in buttons)
