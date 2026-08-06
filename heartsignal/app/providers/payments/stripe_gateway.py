"""Stripe hosted Checkout and subscription adapter.

Vendor objects never leave this module. Only provider-authoritative, privacy-safe facts
cross into the billing services.
"""

import asyncio
import importlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.providers.payments.base import (
    PaymentPayloadError,
    PaymentSignatureError,
    PermanentProviderError,
    ProviderStateMismatch,
    UnknownProviderOutcome,
)
from app.providers.payments.gateway import AuthoritativePayment, CreateCheckout, HostedCheckout
from app.providers.payments.subscription_gateway import (
    CreateSubscriptionCheckout,
    HostedSubscriptionCheckout,
    PaidSubscriptionFact,
    PastDueSubscriptionFact,
    SubscriptionProviderFact,
    SubscriptionStateFact,
)


class StripeGateway:
    def __init__(self, api_key: str, webhook_secret: str, timeout: float = 15) -> None:
        self._stripe = importlib.import_module("stripe")
        self._client = self._stripe.StripeClient(api_key, max_network_retries=0)
        self._webhook_secret = webhook_secret
        self._timeout = timeout

    def verify_webhook(self, payload: bytes, signature: str) -> Mapping[str, object]:
        try:
            event = self._stripe.Webhook.construct_event(payload, signature, self._webhook_secret)
        except self._stripe.SignatureVerificationError as exc:
            raise PaymentSignatureError from exc
        except (ValueError, TypeError) as exc:
            raise PaymentPayloadError from exc
        return dict(event)

    async def create_checkout(self, request: CreateCheckout) -> HostedCheckout:
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.checkout.sessions.create,
                    {
                        "mode": "payment",
                        "line_items": [{"price": request.price_reference, "quantity": 1}],
                        "success_url": request.success_url,
                        "cancel_url": request.cancel_url,
                        "client_reference_id": request.order_id,
                        "metadata": {
                            "order_id": request.order_id,
                            "product_code": request.product_code,
                            "product_version": str(request.product_version),
                        },
                    },
                    options={"idempotency_key": request.idempotency_key},
                ),
                self._timeout,
            )
        except (TimeoutError, self._stripe.APIConnectionError) as exc:
            raise UnknownProviderOutcome from exc
        except self._stripe.StripeError as exc:
            raise PermanentProviderError(type(exc).__name__) from exc
        if not result.id or not result.url:
            raise PermanentProviderError("malformed_checkout")
        expires = datetime.fromtimestamp(result.expires_at, UTC) if result.expires_at else None
        payment_id = str(result.payment_intent) if result.payment_intent else None
        return HostedCheckout(
            result.id,
            result.url,
            str(result.status),
            payment_id,
            expires_at=expires,
            live_mode=bool(result.livemode),
        )

    async def fetch_payment(self, checkout_id: str) -> AuthoritativePayment:
        try:
            value = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.checkout.sessions.retrieve,
                    checkout_id,
                    params={"expand": ["payment_intent"]},
                ),
                self._timeout,
            )
        except (TimeoutError, self._stripe.APIConnectionError) as exc:
            raise UnknownProviderOutcome from exc
        except self._stripe.StripeError as exc:
            raise PermanentProviderError(type(exc).__name__) from exc
        metadata = dict(value.metadata or {})
        intent = value.payment_intent
        payment_id = intent.id if hasattr(intent, "id") else str(intent or "")
        return AuthoritativePayment(
            checkout_id=value.id,
            payment_id=payment_id or value.id,
            status="succeeded" if value.payment_status == "paid" else str(value.status),
            amount_minor=int(value.amount_total or 0),
            currency=str(value.currency or "").upper(),
            order_id=str(metadata.get("order_id") or value.client_reference_id or ""),
            mode=str(value.mode),
            paid=value.payment_status == "paid",
            live_mode=bool(value.livemode),
            provider_status=str(value.payment_status),
        )

    async def create_subscription_checkout(
        self, request: CreateSubscriptionCheckout
    ) -> HostedSubscriptionCheckout:
        metadata = {
            "user_id": str(request.user_id),
            "order_id": str(request.order_id),
            "product_code": request.product_code,
            "product_version": str(request.product_version),
            "market": request.market,
            "currency": request.currency,
            "amount_minor": str(request.amount_minor),
            "credits": str(request.credits),
            "price_reference": request.price_reference,
            "consent_version": request.consent_version,
        }
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.checkout.sessions.create,
                    {
                        "mode": "subscription",
                        "line_items": [{"price": request.price_reference, "quantity": 1}],
                        "success_url": request.success_url,
                        "cancel_url": request.cancel_url,
                        "client_reference_id": str(request.user_id),
                        "metadata": metadata,
                        "subscription_data": {"metadata": metadata},
                    },
                    options={"idempotency_key": request.idempotency_key},
                ),
                self._timeout,
            )
        except (TimeoutError, self._stripe.APIConnectionError) as exc:
            raise UnknownProviderOutcome from exc
        except self._stripe.StripeError as exc:
            raise PermanentProviderError(type(exc).__name__) from exc
        if not result.id or not result.url or str(result.mode) != "subscription":
            raise PermanentProviderError("malformed_subscription_checkout")
        expires = datetime.fromtimestamp(result.expires_at, UTC) if result.expires_at else None
        return HostedSubscriptionCheckout(
            checkout_id=str(result.id),
            url=str(result.url),
            status=str(result.status),
            expires_at=expires,
            live_mode=bool(result.livemode),
        )

    async def fetch_subscription_event(
        self, event_type: str, object_id: str
    ) -> SubscriptionProviderFact:
        if event_type.startswith("checkout.session."):
            session = await self._retrieve_checkout_subscription(object_id)
            subscription = await self._expanded_subscription(_value(session, "subscription"))
            invoice = _value(subscription, "latest_invoice")
            if invoice:
                return self._invoice_fact(invoice, subscription, event_type)
            return self._state_fact(subscription)
        if event_type.startswith("invoice."):
            invoice = await self._retrieve_invoice(object_id)
            subscription = await self._expanded_subscription(_value(invoice, "subscription"))
            return self._invoice_fact(invoice, subscription, event_type)
        subscription = await self._retrieve_subscription(object_id)
        if event_type == "subscription_reconciliation":
            invoice = _value(subscription, "latest_invoice")
            if invoice:
                return self._invoice_fact(invoice, subscription, event_type)
        return self._state_fact(subscription)

    async def fetch_subscription(self, subscription_id: str) -> SubscriptionProviderFact:
        subscription = await self._retrieve_subscription(subscription_id)
        invoice = _value(subscription, "latest_invoice")
        if invoice:
            return self._invoice_fact(invoice, subscription, "subscription_reconciliation")
        return self._state_fact(subscription)

    async def cancel_subscription(self, subscription_id: str) -> SubscriptionStateFact:
        try:
            subscription = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.subscriptions.update,
                    subscription_id,
                    {"cancel_at_period_end": True},
                ),
                self._timeout,
            )
        except (TimeoutError, self._stripe.APIConnectionError) as exc:
            raise UnknownProviderOutcome from exc
        except self._stripe.StripeError as exc:
            raise PermanentProviderError(type(exc).__name__) from exc
        return self._state_fact(subscription)

    async def resume_subscription(self, subscription_id: str) -> SubscriptionStateFact:
        try:
            subscription = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.subscriptions.update,
                    subscription_id,
                    {"cancel_at_period_end": False},
                ),
                self._timeout,
            )
        except (TimeoutError, self._stripe.APIConnectionError) as exc:
            raise UnknownProviderOutcome from exc
        except self._stripe.StripeError as exc:
            raise PermanentProviderError(type(exc).__name__) from exc
        return self._state_fact(subscription)

    async def _retrieve_checkout_subscription(self, checkout_id: str) -> object:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.checkout.sessions.retrieve,
                    checkout_id,
                    params={"expand": ["subscription", "subscription.latest_invoice"]},
                ),
                self._timeout,
            )
        except (TimeoutError, self._stripe.APIConnectionError) as exc:
            raise UnknownProviderOutcome from exc
        except self._stripe.StripeError as exc:
            raise PermanentProviderError(type(exc).__name__) from exc

    async def _retrieve_invoice(self, invoice_id: str) -> object:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.invoices.retrieve,
                    invoice_id,
                    params={"expand": ["subscription", "subscription.latest_invoice"]},
                ),
                self._timeout,
            )
        except (TimeoutError, self._stripe.APIConnectionError) as exc:
            raise UnknownProviderOutcome from exc
        except self._stripe.StripeError as exc:
            raise PermanentProviderError(type(exc).__name__) from exc

    async def _retrieve_subscription(self, subscription_id: str) -> object:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.subscriptions.retrieve,
                    subscription_id,
                    params={"expand": ["latest_invoice"]},
                ),
                self._timeout,
            )
        except (TimeoutError, self._stripe.APIConnectionError) as exc:
            raise UnknownProviderOutcome from exc
        except self._stripe.StripeError as exc:
            raise PermanentProviderError(type(exc).__name__) from exc

    async def _expanded_subscription(self, value: object) -> object:
        if isinstance(value, str):
            return await self._retrieve_subscription(value)
        if value is None:
            raise ProviderStateMismatch("subscription missing")
        return value

    def _invoice_fact(
        self,
        invoice: object,
        subscription: object,
        event_type: str,
    ) -> SubscriptionProviderFact:
        metadata = _metadata(subscription)
        product_code = _required(metadata, "product_code")
        product_version = _int(metadata, "product_version")
        currency = _required(metadata, "currency").upper()
        amount_minor = _int(metadata, "amount_minor")
        credits = _int(metadata, "credits")
        price_reference = _required(metadata, "price_reference")
        consent_version = _required(metadata, "consent_version")
        provider_subscription_id = _required_value(subscription, "id")
        provider_invoice_id = _required_value(invoice, "id")
        provider_payment_id = str(_value(invoice, "payment_intent") or provider_invoice_id)
        actual_currency = str(_value(invoice, "currency") or "").upper()
        actual_amount = int(_value(invoice, "amount_paid") or 0)
        period_start, period_end = _invoice_period(invoice)
        if actual_currency != currency or actual_amount != amount_minor:
            raise ProviderStateMismatch("subscription commercial mismatch")
        status = str(_value(invoice, "status") or "")
        paid = bool(_value(invoice, "paid")) or status == "paid"
        if not paid or event_type in {"invoice.payment_failed", "invoice.payment_action_required"}:
            return PastDueSubscriptionFact(
                provider="stripe",
                provider_subscription_id=provider_subscription_id,
                provider_invoice_id=provider_invoice_id,
                product_code=product_code,
                product_version=product_version,
                currency=currency,
                amount_minor=amount_minor,
                credits=credits,
                period_start=period_start,
                period_end=period_end,
            )
        user_id = UUID(_required(metadata, "user_id"))
        initial_order_id = UUID(metadata["order_id"]) if metadata.get("order_id") else None
        paid_at = datetime.fromtimestamp(
            int(_value(invoice, "status_transitions", "paid_at") or int(datetime.now(UTC).timestamp())),
            UTC,
        )
        return PaidSubscriptionFact(
            user_id=user_id,
            initial_order_id=initial_order_id,
            provider="stripe",
            provider_customer_id=str(_value(subscription, "customer") or ""),
            provider_subscription_id=provider_subscription_id,
            provider_invoice_id=provider_invoice_id,
            provider_payment_id=provider_payment_id,
            product_code=product_code,
            product_version=product_version,
            market=_required(metadata, "market"),
            currency=currency,
            amount_minor=amount_minor,
            credits=credits,
            price_reference=price_reference,
            period_start=period_start,
            period_end=period_end,
            paid_at=paid_at,
            consent_version=consent_version,
            live_mode=bool(_value(invoice, "livemode")),
        )

    def _state_fact(self, subscription: object) -> SubscriptionStateFact:
        metadata = _metadata(subscription)
        return SubscriptionStateFact(
            user_id=UUID(_required(metadata, "user_id")),
            provider="stripe",
            provider_subscription_id=_required_value(subscription, "id"),
            status=str(_value(subscription, "status") or "unknown"),
            current_period_start=_timestamp(_value(subscription, "current_period_start")),
            current_period_end=_timestamp(_value(subscription, "current_period_end")),
            cancel_at_period_end=bool(_value(subscription, "cancel_at_period_end")),
            canceled_at=_timestamp(_value(subscription, "canceled_at")),
        )


def _value(source: object, *path: str) -> Any:
    current = source
    for part in path:
        if isinstance(current, Mapping):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def _metadata(source: object) -> dict[str, str]:
    value = _value(source, "metadata")
    return {str(key): str(item) for key, item in dict(value or {}).items()}


def _required(metadata: dict[str, str], key: str) -> str:
    value = metadata.get(key, "")
    if not value:
        raise ProviderStateMismatch(f"missing subscription metadata: {key}")
    return value


def _required_value(source: object, key: str) -> str:
    value = str(_value(source, key) or "")
    if not value:
        raise ProviderStateMismatch(f"missing provider field: {key}")
    return value


def _int(metadata: dict[str, str], key: str) -> int:
    try:
        value = int(_required(metadata, key))
    except ValueError as exc:
        raise ProviderStateMismatch(f"invalid subscription metadata: {key}") from exc
    if value < 1:
        raise ProviderStateMismatch(f"invalid subscription metadata: {key}")
    return value


def _timestamp(value: object) -> datetime | None:
    return datetime.fromtimestamp(int(value), UTC) if value else None


def _invoice_period(invoice: object) -> tuple[datetime, datetime]:
    lines = _value(invoice, "lines", "data") or []
    if not lines:
        raise ProviderStateMismatch("subscription invoice period missing")
    period = _value(lines[0], "period")
    start = _timestamp(_value(period, "start"))
    end = _timestamp(_value(period, "end"))
    if start is None or end is None or end <= start:
        raise ProviderStateMismatch("subscription invoice period invalid")
    return start, end
