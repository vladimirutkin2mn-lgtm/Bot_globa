"""Server-authoritative Telegram Stars invoices and payment application."""

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import (
    BillingOutboxEvent,
    PaymentOrder,
    ProviderWebhookEvent,
    Subscription,
    User,
)
from app.domain.billing import BillingCatalog, PurchaseMode
from app.providers.payments.base import BillingMarket, PaymentProviderName
from app.providers.payments.gateway import AuthoritativePayment
from app.providers.payments.subscription_gateway import (
    InitialSubscriptionFailedFact,
    PaidSubscriptionFact,
    SubscriptionStateFact,
)
from app.providers.payments.telegram_stars import (
    TELEGRAM_STARS_CURRENCY,
    TELEGRAM_STARS_PROVIDER,
    TELEGRAM_STARS_SUBSCRIPTION_STATES,
)
from app.services.payment_completion_service import PaymentCompletionService
from app.services.subscription_event_processor import SubscriptionEventProcessor
from app.services.subscription_lifecycle import (
    ACTIVE_SUBSCRIPTION_STATUSES,
    SubscriptionLifecycleError,
)

logger = logging.getLogger(__name__)

STARS_PAYLOAD_PREFIX = "globa-stars-v1:"
STARS_SUBSCRIPTION_PERIOD_SECONDS = 2_592_000
# Telegram gives the user seconds to confirm and then charges immediately. A short lease lets an
# abandoned confirmation be retried while a concurrent second invoice message is still refused.
STARS_PRE_CHECKOUT_LEASE = timedelta(seconds=120)


class TelegramStarsRejectedError(RuntimeError):
    """A safe Stars purchase rejection that contains no provider payload."""


class TelegramStarsStateError(RuntimeError):
    """A paid Telegram fact conflicts with durable commercial state."""


@dataclass(frozen=True, slots=True)
class TelegramStarsInvoice:
    order_id: UUID
    payload: str
    title: str
    description: str
    price_label: str
    amount: int
    credits: int
    subscription_period: int | None


@dataclass(frozen=True, slots=True)
class PreCheckoutDecision:
    approved: bool
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class TelegramStarsPaymentFact:
    currency: str
    total_amount: int
    invoice_payload: str
    telegram_payment_charge_id: str
    paid_at: datetime
    subscription_expiration_date: datetime | None = None
    is_recurring: bool = False
    is_first_recurring: bool = False


@dataclass(frozen=True, slots=True)
class TelegramStarsCompletion:
    outcome: str
    order_id: UUID
    credits: int
    subscription: bool


class TelegramStarsPaymentService:
    """Create immutable invoices, validate checkout, and grant paid value once."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: Settings,
        catalog: BillingCatalog,
        completion: PaymentCompletionService,
        subscriptions: SubscriptionEventProcessor,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._catalog = catalog
        self._completion = completion
        self._subscriptions = subscriptions

    async def create_invoice(self, user_id: UUID, product_code: str) -> TelegramStarsInvoice:
        if not self._settings.permits_new_checkout() or not self._settings.telegram_stars_enabled:
            raise TelegramStarsRejectedError("Telegram Stars are unavailable")
        try:
            offer = self._catalog.resolve_product_offer(
                product_code,
                BillingMarket.TELEGRAM,
                TELEGRAM_STARS_CURRENCY,
            )
        except LookupError as exc:
            raise TelegramStarsRejectedError("unsupported Stars offer") from exc
        if offer.provider is not PaymentProviderName.TELEGRAM_STARS:
            raise TelegramStarsRejectedError("unsupported Stars provider")
        if offer.price_reference.startswith("unconfigured:") or offer.amount_minor <= 0:
            raise TelegramStarsRejectedError("Stars price is unavailable")
        subscription = offer.purchase_mode is PurchaseMode.SUBSCRIPTION
        if subscription and not self._settings.subscriptions_enabled:
            raise TelegramStarsRejectedError("Stars subscriptions are unavailable")

        async with self._sessions.begin() as session:
            user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
            if user is None or user.privacy_status != "active":
                raise TelegramStarsRejectedError("active user not found")
            if subscription:
                active = await session.scalar(
                    select(Subscription.id).where(
                        Subscription.user_id == user_id,
                        Subscription.product_code == offer.product_code.value,
                        Subscription.status.in_(ACTIVE_SUBSCRIPTION_STATUSES),
                    )
                )
                if active is not None:
                    raise TelegramStarsRejectedError("subscription already exists")
            order = await session.scalar(
                select(PaymentOrder)
                .where(
                    PaymentOrder.user_id == user_id,
                    PaymentOrder.provider == TELEGRAM_STARS_PROVIDER,
                    PaymentOrder.product_code.in_(offer.active_order_codes),
                    PaymentOrder.market == BillingMarket.TELEGRAM.value,
                    PaymentOrder.currency == TELEGRAM_STARS_CURRENCY,
                    PaymentOrder.status.in_(("creating", "pending")),
                )
                .order_by(PaymentOrder.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            if order is not None:
                return self._invoice_from_order(order)

            order_id = uuid4()
            payload = stars_payload(order_id)
            invoice_title = offer.title[:32]
            period_copy = (
                " Автопродление каждые 30 дней можно отключить в разделе подписки."
                if subscription
                else ""
            )
            description = (
                f"{offer.title}. После подтверждённой оплаты будет начислено "
                f"{offer.credits} кредитов.{period_copy}"
            )[:255]
            price_label = offer.receipt_label[:64]
            order = PaymentOrder(
                id=order_id,
                user_id=user_id,
                provider=TELEGRAM_STARS_PROVIDER,
                product_code=offer.product_code.value,
                status="pending",
                credits=offer.credits,
                amount_minor=offer.amount_minor,
                currency=TELEGRAM_STARS_CURRENCY,
                provider_checkout_id=payload,
                provider_status="invoice_created",
                provider_live_mode=True,
                mode="subscription_initial" if subscription else "one_time",
                market=BillingMarket.TELEGRAM.value,
                product_version=offer.product_version,
                billing_period="month" if subscription else None,
                idempotency_key=f"stars:invoice:{order_id}:v1",
                commercial_snapshot={
                    "product_code": offer.product_code.value,
                    "product_version": offer.product_version,
                    "title": offer.title,
                    "receipt_label": offer.receipt_label,
                    "invoice_title": invoice_title,
                    "invoice_description": description,
                    "invoice_price_label": price_label,
                    "credits": offer.credits,
                    "amount_minor": offer.amount_minor,
                    "currency": TELEGRAM_STARS_CURRENCY,
                    "provider": TELEGRAM_STARS_PROVIDER,
                    "market": BillingMarket.TELEGRAM.value,
                    "price_reference": offer.price_reference,
                    "billing_period": "month" if subscription else None,
                    "consent_version": self._settings.billing_consent_version,
                },
            )
            session.add(order)
            session.add(
                BillingOutboxEvent(
                    aggregate_type="payment_order",
                    aggregate_id=str(order_id),
                    event_type=(
                        "subscription_checkout_started" if subscription else "checkout_started"
                    ),
                    payload={
                        "product_code": offer.product_code.value,
                        "provider": TELEGRAM_STARS_PROVIDER,
                    },
                    idempotency_key=f"stars_invoice_started:{order_id}",
                )
            )
            return self._invoice_from_order(order)

    async def validate_pre_checkout(
        self,
        telegram_user_id: int,
        query_id: str,
        payload: str,
        currency: str,
        total_amount: int,
    ) -> PreCheckoutDecision:
        """Authorize at most one in-flight charge per order, under a row lock.

        One order can back several invoice messages, and Telegram charges as soon as this answer
        is `ok`. Approving two concurrent queries would take the user's Stars twice for a single
        grant, so the authorization is recorded here while the order row is locked. Telegram's own
        retry of the same query id stays idempotent.
        """
        if not self._settings.permits_new_checkout() or not self._settings.telegram_stars_enabled:
            return PreCheckoutDecision(False, "Оплата звёздами временно недоступна.")
        order_id = parse_stars_payload(payload)
        if order_id is None:
            return PreCheckoutDecision(False, "Счёт не найден. Создайте его заново в боте.")
        async with self._sessions.begin() as session:
            # Global lock order: User -> PaymentOrder.
            initial = await session.get(PaymentOrder, order_id)
            if initial is None:
                return PreCheckoutDecision(
                    False,
                    "Параметры счёта изменились. Создайте новый счёт в боте.",
                )
            user = await session.scalar(
                select(User).where(User.id == initial.user_id).with_for_update()
            )
            # The discovery read above already populated this row in the identity map; without
            # populate_existing the locked read would return those stale attributes and two
            # concurrent queries could both see an unauthorized order.
            order = await session.scalar(
                select(PaymentOrder)
                .where(PaymentOrder.id == order_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                order is None
                or user is None
                or user.telegram_user_id != telegram_user_id
                or user.privacy_status != "active"
                or order.provider != TELEGRAM_STARS_PROVIDER
                or order.provider_checkout_id != payload
                or order.status not in {"creating", "pending"}
                or order.currency != currency
                or currency != TELEGRAM_STARS_CURRENCY
                or order.amount_minor != total_amount
            ):
                return PreCheckoutDecision(
                    False,
                    "Параметры счёта изменились. Создайте новый счёт в боте.",
                )
            if order.mode == "subscription_initial" and not self._settings.subscriptions_enabled:
                return PreCheckoutDecision(False, "Подписка временно недоступна.")
            if order.pre_checkout_query_id == query_id:
                return PreCheckoutDecision(True)
            authorized_at = order.pre_checkout_authorized_at
            now = datetime.now(UTC)
            if authorized_at is not None and now - _aware_utc(authorized_at) < (
                STARS_PRE_CHECKOUT_LEASE
            ):
                return PreCheckoutDecision(
                    False,
                    "Этот счёт уже оплачивается. Дождитесь результата, повторно платить не нужно.",
                )
            order.pre_checkout_query_id = query_id[:64]
            order.pre_checkout_authorized_at = now
        return PreCheckoutDecision(True)

    async def complete_successful(
        self,
        telegram_user_id: int,
        payment: TelegramStarsPaymentFact,
    ) -> TelegramStarsCompletion:
        try:
            return await self._complete_successful(telegram_user_id, payment)
        except TelegramStarsStateError:
            await self._record_manual_review(
                telegram_user_id,
                payment,
                "telegram_stars_state_mismatch",
            )
            raise
        except SubscriptionLifecycleError as exc:
            await self._record_manual_review(
                telegram_user_id,
                payment,
                "telegram_stars_subscription_mismatch",
            )
            raise TelegramStarsStateError("Stars subscription requires review") from exc

    async def _complete_successful(
        self,
        telegram_user_id: int,
        payment: TelegramStarsPaymentFact,
    ) -> TelegramStarsCompletion:
        order_id = parse_stars_payload(payment.invoice_payload)
        if order_id is None or not payment.telegram_payment_charge_id.strip():
            raise TelegramStarsStateError("invalid Stars payment identity")
        async with self._sessions() as session:
            order = await session.get(PaymentOrder, order_id)
            user = None if order is None else await session.get(User, order.user_id)
            if (
                order is None
                or user is None
                or user.telegram_user_id != telegram_user_id
                or order.provider != TELEGRAM_STARS_PROVIDER
                or order.provider_checkout_id != payment.invoice_payload
                or order.currency != payment.currency
                or payment.currency != TELEGRAM_STARS_CURRENCY
                or order.amount_minor != payment.total_amount
            ):
                raise TelegramStarsStateError("Stars payment does not match its order")
            if user.privacy_status != "active":
                raise TelegramStarsStateError("Stars payment owner is unavailable")
            snapshot = dict(order.commercial_snapshot)
            subscription = order.mode == "subscription_initial"
            stable_subscription_id: str | None = None
            initial_order_id: UUID | None = None
            if subscription and order.subscription_id is not None:
                stored_subscription = await session.get(Subscription, order.subscription_id)
                if (
                    stored_subscription is None
                    or stored_subscription.user_id != user.id
                    or stored_subscription.provider != TELEGRAM_STARS_PROVIDER
                ):
                    raise TelegramStarsStateError("Stars subscription identity mismatch")
                stable_subscription_id = stored_subscription.provider_subscription_id
            elif subscription:
                if not payment.is_first_recurring:
                    raise TelegramStarsStateError("first Stars subscription payment is missing")
                stable_subscription_id = payment.telegram_payment_charge_id
                initial_order_id = order.id
            user_id = user.id
            credits = order.credits

        if not subscription:
            if payment.is_recurring or payment.subscription_expiration_date is not None:
                raise TelegramStarsStateError("one-time Stars payment marked recurring")
            outcome = await self._completion.complete(
                order_id,
                AuthoritativePayment(
                    checkout_id=payment.invoice_payload,
                    payment_id=payment.telegram_payment_charge_id,
                    status="succeeded",
                    amount_minor=payment.total_amount,
                    currency=payment.currency,
                    order_id=str(order_id),
                    paid=True,
                    live_mode=True,
                    provider_status="paid",
                ),
            )
            if outcome not in {"completed", "already_completed"}:
                await self._record_manual_review(
                    telegram_user_id,
                    payment,
                    "telegram_stars_completion_mismatch",
                )
            return TelegramStarsCompletion(outcome, order_id, credits, False)

        period_end = payment.subscription_expiration_date
        if not payment.is_recurring or period_end is None or stable_subscription_id is None:
            raise TelegramStarsStateError("Stars subscription period is missing")
        period_end = _aware_utc(period_end)
        period_start = period_end - timedelta(seconds=STARS_SUBSCRIPTION_PERIOD_SECONDS)
        await self._subscriptions.apply(
            PaidSubscriptionFact(
                user_id=user_id,
                initial_order_id=initial_order_id,
                provider=TELEGRAM_STARS_PROVIDER,
                provider_customer_id=str(telegram_user_id),
                provider_subscription_id=stable_subscription_id,
                provider_invoice_id=payment.telegram_payment_charge_id,
                provider_payment_id=payment.telegram_payment_charge_id,
                product_code=_snapshot_text(snapshot, "product_code"),
                product_version=_snapshot_int(snapshot, "product_version"),
                market=_snapshot_text(snapshot, "market"),
                currency=payment.currency,
                amount_minor=payment.total_amount,
                credits=credits,
                price_reference=_snapshot_text(snapshot, "price_reference"),
                period_start=period_start,
                period_end=period_end,
                paid_at=_aware_utc(payment.paid_at),
                consent_version=_snapshot_text(snapshot, "consent_version"),
                live_mode=True,
            )
        )
        return TelegramStarsCompletion("completed", order_id, credits, True)

    async def _record_manual_review(
        self,
        telegram_user_id: int,
        payment: TelegramStarsPaymentFact,
        code: str,
    ) -> None:
        digest = hashlib.sha256(
            "\0".join(
                (
                    str(telegram_user_id),
                    payment.currency,
                    str(payment.total_amount),
                    payment.invoice_payload,
                    payment.telegram_payment_charge_id,
                    str(payment.is_recurring),
                    str(payment.is_first_recurring),
                )
            ).encode()
        ).hexdigest()
        provider_event_id = payment.telegram_payment_charge_id.strip() or f"unknown:{digest[:32]}"
        provider_object_id = payment.invoice_payload[:255] or "missing"
        order_id = parse_stars_payload(payment.invoice_payload)
        async with self._sessions.begin() as session:
            initial = None if order_id is None else await session.get(PaymentOrder, order_id)
            if initial is not None:
                await session.scalar(
                    select(User).where(User.id == initial.user_id).with_for_update()
                )
                order = await session.scalar(
                    select(PaymentOrder)
                    .where(PaymentOrder.id == initial.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if order is not None and order.status in {"creating", "pending"}:
                    order.status = "manual_review"
                    order.failure_code = code
            inserted = await session.scalar(
                insert(ProviderWebhookEvent)
                .values(
                    provider=TELEGRAM_STARS_PROVIDER,
                    provider_event_id=provider_event_id,
                    event_type="telegram.successful_payment",
                    provider_object_id=provider_object_id,
                    payload_hash=digest,
                    status="manual_review",
                    attempt_count=0,
                    last_error_code=code,
                )
                .on_conflict_do_nothing(index_elements=["provider", "provider_event_id"])
                .returning(ProviderWebhookEvent.id)
            )
            if inserted is None:
                event = await session.scalar(
                    select(ProviderWebhookEvent)
                    .where(
                        ProviderWebhookEvent.provider == TELEGRAM_STARS_PROVIDER,
                        ProviderWebhookEvent.provider_event_id == provider_event_id,
                    )
                    .with_for_update()
                )
                if event is None:
                    raise RuntimeError("Stars manual-review event disappeared")
            else:
                event = None
            if event is not None and (
                event.payload_hash != digest or event.provider_object_id != provider_object_id
            ):
                event.status = "manual_review"
                event.last_error_code = "duplicate_payload_mismatch"

    async def apply_subscription_update(
        self,
        telegram_user_id: int,
        payload: str,
        state: str,
    ) -> bool:
        order_id = parse_stars_payload(payload)
        if order_id is None:
            return False
        if state not in TELEGRAM_STARS_SUBSCRIPTION_STATES:
            # A state Telegram adds later must be visible, not silently dropped: an unapplied
            # cancellation would keep a local subscription entitled after the provider stopped.
            logger.warning("telegram_stars_subscription_state_unhandled state=%r", state[:32])
            return False
        async with self._sessions() as session:
            order = await session.get(PaymentOrder, order_id)
            user = None if order is None else await session.get(User, order.user_id)
            if (
                order is None
                or user is None
                or user.telegram_user_id != telegram_user_id
                or order.provider != TELEGRAM_STARS_PROVIDER
                or order.mode != "subscription_initial"
                or order.provider_checkout_id != payload
            ):
                return False
            subscription = (
                None
                if order.subscription_id is None
                else await session.get(Subscription, order.subscription_id)
            )
            user_id = user.id
            fact: InitialSubscriptionFailedFact | SubscriptionStateFact
            if subscription is None:
                if state not in {"canceled", "failed"}:
                    return False
                fact = InitialSubscriptionFailedFact(
                    user_id=user_id,
                    order_id=order.id,
                    provider=TELEGRAM_STARS_PROVIDER,
                    provider_payment_id=payload,
                    provider_status=state,
                )
            else:
                fact = SubscriptionStateFact(
                    user_id=user_id,
                    provider=TELEGRAM_STARS_PROVIDER,
                    provider_subscription_id=subscription.provider_subscription_id,
                    status=state,
                    current_period_start=subscription.current_period_start,
                    current_period_end=subscription.current_period_end,
                    cancel_at_period_end=state == "canceled",
                )
        return await self._subscriptions.apply(fact)

    @staticmethod
    def _invoice_from_order(order: PaymentOrder) -> TelegramStarsInvoice:
        snapshot = dict(order.commercial_snapshot)
        payload = order.provider_checkout_id
        if payload is None or parse_stars_payload(payload) != order.id:
            raise TelegramStarsStateError("stored Stars invoice identity is invalid")
        return TelegramStarsInvoice(
            order_id=order.id,
            payload=payload,
            title=_snapshot_text(snapshot, "invoice_title"),
            description=_snapshot_text(snapshot, "invoice_description"),
            price_label=_snapshot_text(snapshot, "invoice_price_label"),
            amount=order.amount_minor,
            credits=order.credits,
            subscription_period=(
                STARS_SUBSCRIPTION_PERIOD_SECONDS if order.mode == "subscription_initial" else None
            ),
        )


def stars_payload(order_id: UUID) -> str:
    return f"{STARS_PAYLOAD_PREFIX}{order_id.hex}"


def parse_stars_payload(payload: str) -> UUID | None:
    if not payload.startswith(STARS_PAYLOAD_PREFIX):
        return None
    encoded = payload.removeprefix(STARS_PAYLOAD_PREFIX)
    if len(encoded) != 32:
        return None
    try:
        return UUID(hex=encoded)
    except ValueError:
        return None


def _snapshot_text(snapshot: dict[str, object], key: str) -> str:
    value = snapshot.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TelegramStarsStateError("stored Stars commercial snapshot is incomplete")
    return value.strip()


def _snapshot_int(snapshot: dict[str, object], key: str) -> int:
    value = snapshot.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TelegramStarsStateError("stored Stars commercial snapshot is incomplete")
    return value


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TelegramStarsStateError("Stars timestamp is timezone-naive")
    return value.astimezone(UTC)
