"""Stripe SDK-boundary acceptance for catalog-v2 one-time products."""

from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.providers.payments.gateway import CreateCheckout
from app.providers.payments.stripe_gateway import StripeGateway


class StripeError(Exception):
    pass


class APIConnectionError(StripeError):
    pass


class SignatureVerificationError(StripeError):
    pass


class FakeSessions:
    def __init__(self) -> None:
        self.created: tuple[dict[str, object], dict[str, str]] | None = None

    def create(self, params: dict[str, object], *, options: dict[str, str]) -> object:
        self.created = params, options
        return SimpleNamespace(
            id="cs_catalog_v2",
            url="https://checkout.stripe.test/cs_catalog_v2",
            status="open",
            expires_at=1_800_000_000,
            payment_intent=None,
            livemode=False,
        )


class FakeStripe:
    APIConnectionError = APIConnectionError
    StripeError = StripeError
    SignatureVerificationError = SignatureVerificationError


@pytest.mark.asyncio
async def test_one_time_checkout_uses_server_price_and_canonical_sku_metadata() -> None:
    value = object.__new__(StripeGateway)
    sessions = FakeSessions()
    dynamic = cast("Any", value)
    dynamic._stripe = FakeStripe()
    dynamic._client = SimpleNamespace(checkout=SimpleNamespace(sessions=sessions))
    dynamic._webhook_secret = "whsec_test"
    dynamic._timeout = 1
    request = CreateCheckout(
        order_id="00000000-0000-0000-0000-000000000405",
        product_code="astrology_forecast",
        product_version=2,
        amount_minor=1_990,
        currency="EUR",
        price_reference="price_approved_single_eur",
        idempotency_key="checkout:catalog-v2:stripe",
        success_url="https://pay.example/success",
        cancel_url="https://pay.example/cancel",
        receipt_label="Персональный астрологический прогноз",
    )

    checkout = await value.create_checkout(request)

    assert checkout.checkout_id == "cs_catalog_v2"
    assert sessions.created is not None
    params, options = sessions.created
    assert params["mode"] == "payment"
    assert params["line_items"] == [{"price": "price_approved_single_eur", "quantity": 1}]
    assert params["client_reference_id"] == request.order_id
    # The product marker lets one provider account serve several products without their
    # webhooks reading each other's events.
    assert params["metadata"] == {
        "product": "bot_globa",
        "order_id": request.order_id,
        "product_code": "astrology_forecast",
        "product_version": "2",
    }
    assert options == {"idempotency_key": request.idempotency_key}
