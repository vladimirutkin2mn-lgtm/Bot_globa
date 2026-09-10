"""Real PostgreSQL checkout creation concurrency."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import PaymentOrder, User
from app.db.reading_models import Persona, Reading
from app.domain.billing import BillingCatalog
from app.domain.reading_checkout_resume import ReadingCheckoutTarget
from app.providers.payments.base import PaymentProviderName, UnknownProviderOutcomeError
from app.providers.payments.gateway import CreateCheckout, HostedCheckout
from app.services.checkout_service import CheckoutRejectedError, CheckoutService

pytestmark = pytest.mark.postgres


class IdempotentGateway:
    def __init__(self, timeout_once: bool = False) -> None:
        self.keys: list[str] = []
        self.timeout_once = timeout_once

    async def create_checkout(self, request: CreateCheckout) -> HostedCheckout:
        self.keys.append(request.idempotency_key)
        if self.timeout_once:
            self.timeout_once = False
            raise UnknownProviderOutcomeError
        return HostedCheckout("yk-one", "https://provider.test/one", "pending")

    async def fetch_payment(self, checkout_id: str):  # type: ignore[no-untyped-def]
        raise AssertionError


async def _user(sessions: async_sessionmaker[AsyncSession]) -> User:
    async with sessions.begin() as session:
        user = User(telegram_user_id=99112233, first_name="Checkout")
        session.add(user)
        await session.flush()
        return user


async def _reading(
    sessions: async_sessionmaker[AsyncSession],
    user_id: UUID,
    *,
    persona_code: str = "tarot_reader",
) -> Reading:
    async with sessions.begin() as session:
        persona = await session.scalar(select(Persona).where(Persona.code == persona_code))
        if persona is None:
            persona = Persona(
                code=persona_code,
                display_name="Test persona",
                prompt_version="test-v1",
                schema_version="reading-result-v1",
            )
            session.add(persona)
            await session.flush()
        reading = Reading(
            user_id=user_id,
            persona_id=persona.id,
            topic="decision",
            status="preview_ready",
            access_level="preview",
            engine_version="test-v1",
            prompt_version="test-v1",
            schema_version="reading-result-v1",
            symbol_set_code="none",
            generated_at=datetime.now(UTC),
        )
        session.add(reading)
        await session.flush()
        return reading


def _settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "billing_enabled": True,
            "yookassa_enabled": True,
            "yookassa_receipts_required": True,
            "checkout_creation_lease_seconds": 1,
        }
    )


async def test_ten_checkout_requests_create_one_order_and_provider_checkout(
    payment_db: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    user = await _user(payment_db)
    gateway = IdempotentGateway()
    configured = _settings(settings)
    service = CheckoutService(
        payment_db, configured, BillingCatalog(configured), {PaymentProviderName.YOOKASSA: gateway}
    )
    results = await asyncio.gather(
        *(
            service.create_one_time_checkout(
                user.id, "reading_single", "RU", "RUB", receipt_contact="buyer@example.com"
            )
            for _ in range(10)
        )
    )
    async with payment_db() as session:
        count = await session.scalar(select(func.count()).select_from(PaymentOrder))
        order = await session.scalar(select(PaymentOrder))
    assert count == 1 and len(gateway.keys) == 1
    assert order is not None and gateway.keys == [order.idempotency_key]
    assert sum(result.url == "https://provider.test/one" for result in results) >= 1
    assert all(result.url in {None, "https://provider.test/one"} for result in results)
    assert order.encrypted_receipt_contact is None


async def test_ambiguous_checkout_recovers_with_same_key_and_encrypted_contact(
    payment_db: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    user = await _user(payment_db)
    gateway = IdempotentGateway(timeout_once=True)
    configured = _settings(settings)
    service = CheckoutService(
        payment_db, configured, BillingCatalog(configured), {PaymentProviderName.YOOKASSA: gateway}
    )
    first = await service.create_one_time_checkout(
        user.id, "reading_single", "RU", "RUB", receipt_contact="buyer@example.com"
    )
    async with payment_db.begin() as session:
        order = await session.get(PaymentOrder, first.order_id)
        assert order is not None and order.encrypted_receipt_contact is not None
        assert b"buyer@example.com" not in order.encrypted_receipt_contact
        assert "buyer@example.com" not in str(order.commercial_snapshot)
        order.checkout_creation_started_at = datetime.now(UTC) - timedelta(seconds=5)
    second = await service.create_one_time_checkout(
        user.id, "reading_single", "RU", "RUB", receipt_contact="buyer@example.com"
    )
    assert second.url == "https://provider.test/one"
    assert gateway.keys[0] == gateway.keys[1]
    async with payment_db() as session:
        order = await session.get(PaymentOrder, first.order_id)
        assert order is not None and order.encrypted_receipt_contact is None


async def test_reading_target_is_authorized_persisted_and_reused_only_for_same_reading(
    payment_db: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    user = await _user(payment_db)
    reading = await _reading(payment_db, user.id)
    target = ReadingCheckoutTarget(reading.id, "tarot_reader")
    gateway = IdempotentGateway()
    configured = _settings(settings)
    service = CheckoutService(
        payment_db, configured, BillingCatalog(configured), {PaymentProviderName.YOOKASSA: gateway}
    )

    first = await service.create_one_time_checkout(
        user.id,
        "reading_single",
        "RU",
        "RUB",
        receipt_contact="buyer@example.com",
        reading_target=target,
    )
    second = await service.create_one_time_checkout(
        user.id,
        "reading_single",
        "RU",
        "RUB",
        receipt_contact="buyer@example.com",
        reading_target=target,
    )

    async with payment_db() as session:
        order = await session.get(PaymentOrder, first.order_id)
    assert order is not None
    assert order.commercial_snapshot["resume_target"] == target.snapshot()
    assert second.order_id == first.order_id
    assert len(gateway.keys) == 1


async def test_active_checkout_cannot_be_retargeted_to_another_reading_or_generic_purchase(
    payment_db: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    user = await _user(payment_db)
    first_reading = await _reading(payment_db, user.id)
    second_reading = await _reading(payment_db, user.id)
    first_target = ReadingCheckoutTarget(first_reading.id, "tarot_reader")
    second_target = ReadingCheckoutTarget(second_reading.id, "tarot_reader")
    gateway = IdempotentGateway()
    configured = _settings(settings)
    service = CheckoutService(
        payment_db, configured, BillingCatalog(configured), {PaymentProviderName.YOOKASSA: gateway}
    )
    first = await service.create_one_time_checkout(
        user.id,
        "reading_single",
        "RU",
        "RUB",
        receipt_contact="buyer@example.com",
        reading_target=first_target,
    )

    with pytest.raises(CheckoutRejectedError, match="another checkout is already active"):
        await service.create_one_time_checkout(
            user.id,
            "reading_single",
            "RU",
            "RUB",
            receipt_contact="buyer@example.com",
            reading_target=second_target,
        )
    with pytest.raises(CheckoutRejectedError, match="another checkout is already active"):
        await service.create_one_time_checkout(
            user.id,
            "reading_single",
            "RU",
            "RUB",
            receipt_contact="buyer@example.com",
        )

    async with payment_db() as session:
        order = await session.get(PaymentOrder, first.order_id)
        count = await session.scalar(select(func.count()).select_from(PaymentOrder))
    assert order is not None
    assert order.commercial_snapshot["resume_target"] == first_target.snapshot()
    assert count == 1
    assert len(gateway.keys) == 1


async def test_foreign_or_wrong_persona_reading_target_is_rejected_before_provider_call(
    payment_db: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    buyer = await _user(payment_db)
    async with payment_db.begin() as session:
        other = User(telegram_user_id=99112234, first_name="Other")
        session.add(other)
        await session.flush()
        other_id = other.id
    foreign_reading = await _reading(payment_db, other_id)
    own_reading = await _reading(payment_db, buyer.id)
    gateway = IdempotentGateway()
    configured = _settings(settings)
    service = CheckoutService(
        payment_db, configured, BillingCatalog(configured), {PaymentProviderName.YOOKASSA: gateway}
    )

    for target in (
        ReadingCheckoutTarget(foreign_reading.id, "tarot_reader"),
        ReadingCheckoutTarget(own_reading.id, "love_oracle"),
    ):
        with pytest.raises(CheckoutRejectedError, match="reading unavailable"):
            await service.create_one_time_checkout(
                buyer.id,
                "reading_single",
                "RU",
                "RUB",
                receipt_contact="buyer@example.com",
                reading_target=target,
            )

    async with payment_db() as session:
        count = await session.scalar(select(func.count()).select_from(PaymentOrder))
    assert count == 0
    assert gateway.keys == []
