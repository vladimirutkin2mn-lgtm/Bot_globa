"""Only terminal YooKassa outcomes may enter the durable webhook inbox.

Completion treats `waiting_for_capture` as `unexpected_waiting_for_capture` and parks the
order in `manual_review`, which the stale-order sweeper deliberately ignores. Accepting the
hold notification therefore turns a payment that captures a moment later into money taken
against an order nothing will ever complete.
"""

from app.api.webhooks import YOOKASSA_PAYMENT_EVENTS


def test_only_terminal_payment_outcomes_are_accepted() -> None:
    assert sorted(YOOKASSA_PAYMENT_EVENTS) == ["payment.canceled", "payment.succeeded"]


def test_a_hold_notification_is_never_accepted() -> None:
    assert "payment.waiting_for_capture" not in YOOKASSA_PAYMENT_EVENTS
