"""YooKassa sandbox contract for catalog-v2 labels and immutable metadata."""

from typing import ClassVar, cast

import pytest

from app.providers.payments.gateway import CreateCheckout
from app.providers.payments.yookassa_gateway import YooKassaGateway


class FakeResponse:
    status_code = 200
    headers: ClassVar[dict[str, str]] = {"X-Request-Id": "request-label"}

    def json(self) -> dict[str, object]:
        return {
            "id": "payment-label",
            "status": "pending",
            "test": True,
            "confirmation": {"confirmation_url": "https://pay.test/payment-label"},
        }


class FakeHttpClient:
    def __init__(self) -> None:
        self.payload: dict[str, object] | None = None

    async def __aenter__(self) -> "FakeHttpClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(
        self,
        _url: str,
        *,
        auth: tuple[str, str],
        headers: dict[str, str],
        json: dict[str, object],
    ) -> FakeResponse:
        assert auth == ("shop", "secret")
        assert headers["Idempotence-Key"] == "checkout:catalog:v2"
        self.payload = json
        return FakeResponse()


@pytest.mark.asyncio
async def test_one_time_checkout_uses_receipt_label_but_keeps_order_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeHttpClient()
    monkeypatch.setattr(
        "app.providers.payments.yookassa_gateway.httpx.AsyncClient",
        lambda **_: transport,
    )
    request = CreateCheckout(
        order_id="00000000-0000-0000-0000-000000000405",
        product_code="astrology_natal",
        product_version=2,
        amount_minor=19_900,
        currency="RUB",
        price_reference="catalog:astrology_natal:rub:v2",
        idempotency_key="checkout:catalog:v2",
        success_url="https://pay.example/return",
        cancel_url="https://pay.example/cancel",
        receipt_contact="buyer@example.com",
        receipt_label="Персональный натальный профиль",
    )

    await YooKassaGateway("shop", "secret").create_checkout(request)

    assert transport.payload is not None
    receipt = cast("dict[str, object]", transport.payload["receipt"])
    items = cast("list[dict[str, object]]", receipt["items"])
    metadata = cast("dict[str, object]", transport.payload["metadata"])
    assert transport.payload["description"] == request.receipt_label
    assert items[0]["description"] == request.receipt_label
    assert metadata == {
        "product": "bot_globa",
        "order_id": request.order_id,
        "product_version": 2,
    }
    assert request.product_code not in str(receipt)
