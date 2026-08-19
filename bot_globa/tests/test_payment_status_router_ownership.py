from app.bot import core_handlers, subscription_handlers
from app.bot.payment_status_handlers import (
    _PAYMENT_BALANCE_CALLBACKS,
    _SUBSCRIPTION_STATUS_CALLBACK,
    balance_with_payment_status,
)


def test_generic_balance_callbacks_belong_to_payment_status_handler() -> None:
    core_callbacks = [handler.callback for handler in core_handlers.router.callback_query.handlers]

    assert _PAYMENT_BALANCE_CALLBACKS == {"menu:balance", "credits:refresh"}
    assert core_handlers.balance_screen not in core_callbacks
    assert core_callbacks.count(balance_with_payment_status) == 1


def test_subscription_router_keeps_only_its_own_status_refresh_handler() -> None:
    subscription_callbacks = [
        handler.callback for handler in subscription_handlers.router.callback_query.handlers
    ]

    assert _SUBSCRIPTION_STATUS_CALLBACK == "subscription:refresh"
    assert subscription_callbacks.count(subscription_handlers.balance_and_subscription_screen) == 1
    assert _PAYMENT_BALANCE_CALLBACKS.isdisjoint({_SUBSCRIPTION_STATUS_CALLBACK})
