"""One provider account, several products: only our own events reach the inbox.

A provider fans every subscribed event out to every configured endpoint, so this
service receives payments that belong to a different product sharing the account.
Those must be dropped before the durable inbox — and, more importantly, our own
subscription renewals must never be dropped with them.
"""

import pytest

from app.api.webhooks import (
    PRODUCT_MARKER_KEY,
    STRIPE_PAYMENT_EVENTS,
    YOOKASSA_PAYMENT_EVENTS,
    event_belongs_to_this_product,
)
from app.platform.identity import PRODUCT_IDENTITY

OURS = {PRODUCT_MARKER_KEY: PRODUCT_IDENTITY.repository_slug}
THEIRS = {PRODUCT_MARKER_KEY: "some_other_product"}

CHECKOUT_EVENTS = sorted(
    event for event in STRIPE_PAYMENT_EVENTS if event.startswith("checkout.session.")
)
SUBSCRIPTION_EVENTS = sorted(
    event
    for event in STRIPE_PAYMENT_EVENTS
    if event.startswith(("invoice.", "customer.subscription."))
)


@pytest.mark.parametrize("event", CHECKOUT_EVENTS)
def test_a_checkout_without_our_marker_is_not_ours(event: str) -> None:
    """We stamp every checkout we create, so an unmarked one belongs to someone else."""
    assert event_belongs_to_this_product(event, OURS)
    assert not event_belongs_to_this_product(event, THEIRS)
    assert not event_belongs_to_this_product(event, {})


@pytest.mark.parametrize("event", SUBSCRIPTION_EVENTS)
def test_an_unmarked_subscription_event_is_kept_because_the_marker_lives_elsewhere(
    event: str,
) -> None:
    """Stripe sends invoice payloads whose metadata is empty; ours is on the subscription.

    Dropping these on a missing marker would silently discard real renewals, so they are
    only rejected when the payload names a different product.
    """
    assert event_belongs_to_this_product(event, {})
    assert event_belongs_to_this_product(event, OURS)
    assert not event_belongs_to_this_product(event, THEIRS)


@pytest.mark.parametrize("event", sorted(YOOKASSA_PAYMENT_EVENTS))
def test_a_yookassa_payment_requires_our_marker(event: str) -> None:
    assert event_belongs_to_this_product(event, OURS)
    assert not event_belongs_to_this_product(event, THEIRS)
    assert not event_belongs_to_this_product(event, {})


def test_the_marker_is_the_product_identity_rather_than_a_loose_string() -> None:
    assert PRODUCT_IDENTITY.repository_slug == "bot_globa"
    assert not event_belongs_to_this_product(
        "checkout.session.completed", {PRODUCT_MARKER_KEY: "Bot_Globa"}
    )
