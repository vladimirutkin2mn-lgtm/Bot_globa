"""Authenticated, size-bounded production payment webhook endpoints."""

import hashlib
import ipaddress
import json
import logging
from collections.abc import Mapping

from fastapi import APIRouter, HTTPException, Request

from app.platform.identity import PRODUCT_IDENTITY
from app.providers.payments.base import (
    PaymentPayloadError,
    PaymentProviderName,
    PaymentSignatureError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["payment-webhooks"])
STRIPE_PAYMENT_EVENTS = {
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
    "checkout.session.expired",
    "invoice.paid",
    "invoice.payment_failed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}
PRODUCT_MARKER_KEY = "product"


def event_belongs_to_this_product(event_type: str, metadata: Mapping[str, object]) -> bool:
    """Decide whether a provider event was created by this product.

    One provider account can serve several products, and a provider fans every subscribed
    event out to every configured endpoint. Checkouts we create always carry the marker,
    so a checkout without it belongs to someone else and is dropped before it reaches the
    durable inbox.

    Invoice and subscription payloads are different: the marker lives on the subscription,
    not on the object the provider sends. Dropping those on a missing marker would discard
    our own renewals, so they are only rejected when a marker is present and names another
    product. Anything that slips through resolves to `order_not_found`, which is terminal
    and writes nothing to the ledger.
    """
    marker = metadata.get(PRODUCT_MARKER_KEY)
    if event_type.startswith("checkout.session.") or event_type.startswith("payment."):
        return marker == PRODUCT_IDENTITY.repository_slug
    return marker is None or marker == PRODUCT_IDENTITY.repository_slug


# Only terminal outcomes are accepted. Every checkout this product creates carries
# `capture: true`, so a hold is never expected — and `payment.waiting_for_capture` is not a
# harmless extra notification: completion treats that state as `unexpected_waiting_for_capture`
# and parks the order in `manual_review`, which the stale-order sweeper no longer looks at.
# A hold that later captures would then be money taken against a permanently dead order, so
# the notification is dropped and the terminal `payment.succeeded` does the work.
YOOKASSA_PAYMENT_EVENTS = {
    "payment.succeeded",
    "payment.canceled",
}


def resolve_source_ip(peer: str, headers: Mapping[str, str], trusted: str) -> str:
    """Resolve forwarding only from a trusted direct peer; reject ambiguous syntax."""
    try:
        direct = ipaddress.ip_address(peer)
        trusted_nets = [ipaddress.ip_network(x.strip()) for x in trusted.split(",") if x.strip()]
    except ValueError as exc:
        raise PaymentPayloadError("invalid source address") from exc
    forwarded = headers.get("forwarded")
    xff = headers.get("x-forwarded-for")
    if not forwarded and not xff:
        return str(direct)
    if not any(direct in network for network in trusted_nets):
        raise PaymentSignatureError("untrusted forwarding peer")
    if forwarded and xff:
        raise PaymentPayloadError("ambiguous forwarding headers")
    raw = xff or forwarded or ""
    if forwarded:
        parts = []
        for element in raw.split(","):
            fields = dict(item.strip().split("=", 1) for item in element.split(";") if "=" in item)
            if "for" not in fields:
                raise PaymentPayloadError("malformed Forwarded header")
            parts.append(fields["for"].strip('"[]'))
    else:
        parts = [part.strip() for part in raw.split(",")]
    try:
        chain = [ipaddress.ip_address(part) for part in parts]
    except ValueError as exc:
        raise PaymentPayloadError("malformed forwarding chain") from exc
    # Walk right-to-left over trusted hops; the first non-trusted address is the client.
    candidate = direct
    for address in reversed(chain):
        if not any(candidate in network for network in trusted_nets):
            break
        candidate = address
    return str(candidate)


def source_is_allowed(source: str, allowlist: str) -> bool:
    try:
        address = ipaddress.ip_address(source)
        return any(
            address in ipaddress.ip_network(value.strip())
            for value in allowlist.split(",")
            if value.strip()
        )
    except ValueError:
        return False


async def _body(request: Request) -> bytes:
    limit = request.app.state.settings.payment_webhook_max_bytes
    content_length = request.headers.get("content-length")
    if content_length and (not content_length.isdigit() or int(content_length) > limit):
        raise HTTPException(413, "payload too large")
    value = await request.body()
    if len(value) > limit:
        raise HTTPException(413, "payload too large")
    return value


@router.post("/stripe")
async def stripe_webhook(request: Request) -> dict[str, str]:
    body = await _body(request)
    signature = request.headers.get("stripe-signature")
    if not signature:
        raise HTTPException(401, "invalid signature")
    gateway = request.app.state.payment_gateways.get(PaymentProviderName.STRIPE)
    if gateway is None:
        raise HTTPException(503, "provider unavailable")
    try:
        event = gateway.verify_webhook(body, signature)
        data = event.get("data")
        obj = data.get("object") if isinstance(data, dict) else None
        event_id, event_type = str(event["id"]), str(event["type"])
        object_id = str(obj["id"]) if isinstance(obj, dict) else ""
        if not event_id or not object_id:
            raise PaymentPayloadError
    except PaymentSignatureError:
        raise HTTPException(401, "invalid signature") from None
    except (PaymentPayloadError, KeyError, TypeError):
        raise HTTPException(400, "malformed event") from None
    if event_type not in STRIPE_PAYMENT_EVENTS:
        return {"status": "ignored"}
    metadata = obj.get("metadata") if isinstance(obj, dict) else None
    if not event_belongs_to_this_product(
        event_type, metadata if isinstance(metadata, dict) else {}
    ):
        return {"status": "ignored"}
    await request.app.state.webhook_inbox.accept(
        "stripe", event_id, event_type, object_id, hashlib.sha256(body).hexdigest()
    )
    return {"status": "accepted"}


@router.post("/yookassa")
async def yookassa_webhook(request: Request) -> dict[str, str]:
    body = await _body(request)
    settings = request.app.state.settings
    if (
        not settings.yookassa_enabled
        or PaymentProviderName.YOOKASSA not in request.app.state.payment_gateways
    ):
        raise HTTPException(503, "provider unavailable")
    peer = request.client.host if request.client else ""
    # YooKassa authenticates by source address alone, so a rejection here silently discards a
    # real payment notification. Both rejections name the address that failed and which list
    # it failed against: behind a reverse proxy the peer is the proxy, and an empty
    # YOOKASSA_TRUSTED_PROXY_ALLOWLIST rejects every forwarded request before the provider
    # allowlist is ever consulted.
    try:
        source = resolve_source_ip(peer, request.headers, settings.yookassa_trusted_proxy_allowlist)
    except (PaymentPayloadError, PaymentSignatureError) as exc:
        logger.warning(
            "yookassa_webhook_rejected reason=forwarding peer=%s detail=%s "
            "(check YOOKASSA_TRUSTED_PROXY_ALLOWLIST)",
            peer,
            exc,
        )
        raise HTTPException(403, "invalid source") from None
    if not source_is_allowed(source, settings.yookassa_webhook_ip_allowlist):
        logger.warning(
            "yookassa_webhook_rejected reason=source_not_allowed peer=%s source=%s "
            "(check YOOKASSA_WEBHOOK_IP_ALLOWLIST)",
            peer,
            source,
        )
        raise HTTPException(403, "invalid source")
    try:
        value = json.loads(body)
        provider_event_type = str(value["event"])
        obj = value["object"]
        object_id = str(obj["id"])
        metadata = obj.get("metadata", {}) if isinstance(obj, dict) else {}
        if not object_id:
            raise ValueError
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise HTTPException(400, "malformed event") from None
    if provider_event_type not in YOOKASSA_PAYMENT_EVENTS:
        return {"status": "ignored"}
    if not event_belongs_to_this_product(
        provider_event_type, metadata if isinstance(metadata, dict) else {}
    ):
        return {"status": "ignored"}
    subscription = isinstance(metadata, dict) and metadata.get("billing_mode") == "subscription"
    event_type = provider_event_type
    if subscription:
        event_type = (
            "invoice.paid"
            if provider_event_type == "payment.succeeded"
            else "invoice.payment_failed"
        )
    event_id = hashlib.sha256(f"yookassa:{provider_event_type}:{object_id}".encode()).hexdigest()
    await request.app.state.webhook_inbox.accept(
        "yookassa", event_id, event_type, object_id, hashlib.sha256(body).hexdigest()
    )
    return {"status": "accepted"}
