"""Telegram Bot API adapters for Stars refunds and subscription controls."""

import logging
from typing import Protocol

from aiogram.enums import BotSubscriptionUpdatedState
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import StarTransactions, TransactionPartnerUser

from app.providers.payments.base import (
    PermanentProviderError,
    UnknownProviderOutcomeError,
)
from app.providers.payments.refund_gateway import (
    AuthoritativeRefund,
    CreateRefund,
    RefundCapabilities,
)

logger = logging.getLogger(__name__)

TELEGRAM_STARS_PROVIDER = "telegram_stars"
TELEGRAM_STARS_CURRENCY = "XTR"
# The complete set of `BotSubscriptionUpdated.state` values this integration understands.
TELEGRAM_STARS_SUBSCRIPTION_STATES = frozenset(
    {
        BotSubscriptionUpdatedState.ACTIVE.value,
        BotSubscriptionUpdatedState.CANCELED.value,
        BotSubscriptionUpdatedState.FAILED.value,
    }
)
_REFUND_ID_PREFIX = "stars-refund:"


class TelegramStarsBot(Protocol):
    """Narrow Bot API surface used by the billing adapters."""

    async def refund_star_payment(
        self,
        user_id: int,
        telegram_payment_charge_id: str,
        request_timeout: int | None = None,
    ) -> bool: ...

    async def get_star_transactions(
        self,
        offset: int | None = None,
        limit: int | None = None,
        request_timeout: int | None = None,
    ) -> StarTransactions: ...

    async def edit_user_star_subscription(
        self,
        user_id: int,
        telegram_payment_charge_id: str,
        is_canceled: bool,
        request_timeout: int | None = None,
    ) -> bool: ...


class TelegramStarsSubscriptionControl(Protocol):
    async def set_subscription_canceled(
        self,
        telegram_user_id: int,
        telegram_payment_charge_id: str,
        *,
        is_canceled: bool,
    ) -> None: ...


class TelegramStarsGateway:
    """Full-refund and recurring-control adapter over the Telegram Bot API.

    A Stars refund uses the original charge ID as its stable identity. Telegram exposes
    that same ID on the outgoing refund transaction, so an ambiguous network outcome can
    be reconciled without issuing a second financial operation.
    """

    refund_capabilities = RefundCapabilities(partial_refunds=False)

    def __init__(
        self,
        bot: TelegramStarsBot,
        timeout_seconds: float,
        reconciliation_pages: int,
    ) -> None:
        self._bot = bot
        self._timeout = max(1, int(timeout_seconds))
        self._pages = reconciliation_pages

    async def create_refund(self, request: CreateRefund) -> AuthoritativeRefund:
        if request.currency != TELEGRAM_STARS_CURRENCY or request.amount_minor <= 0:
            raise PermanentProviderError("telegram_stars_refund_terms_invalid")
        try:
            telegram_user_id = int(request.provider_customer_id or "")
        except ValueError as exc:
            raise PermanentProviderError("telegram_stars_refund_user_missing") from exc
        try:
            accepted = await self._bot.refund_star_payment(
                telegram_user_id,
                request.provider_payment_id,
                request_timeout=self._timeout,
            )
        except TelegramBadRequest as exc:
            reconciled = await self._try_reconcile(
                request.provider_payment_id,
                telegram_user_id,
                request.amount_minor,
            )
            if reconciled is not None:
                return reconciled
            # A duplicate refund and an invalid request can both surface as a 400. If the
            # bounded transaction scan cannot distinguish them, retain the credit reservation
            # and retry/manual-review instead of releasing value after a possible refund.
            raise UnknownProviderOutcomeError("telegram_stars_refund_unknown") from exc
        except TelegramAPIError as exc:
            reconciled = await self._try_reconcile(
                request.provider_payment_id,
                telegram_user_id,
                request.amount_minor,
            )
            if reconciled is not None:
                return reconciled
            raise UnknownProviderOutcomeError("telegram_stars_refund_unknown") from exc
        if not accepted:
            raise UnknownProviderOutcomeError("telegram_stars_refund_unknown")
        return self._fact(request.provider_payment_id, request.amount_minor)

    async def fetch_refund(self, refund_id: str) -> AuthoritativeRefund:
        charge_id = _charge_id_from_refund_id(refund_id)
        if charge_id is None:
            raise PermanentProviderError("telegram_stars_refund_identity_invalid")
        try:
            found = await self._find_refund(charge_id)
        except TelegramAPIError as exc:
            raise UnknownProviderOutcomeError("telegram_stars_refund_lookup_failed") from exc
        if found is None:
            raise UnknownProviderOutcomeError("telegram_stars_refund_not_visible")
        amount, _ = found
        return self._fact(charge_id, amount)

    async def set_subscription_canceled(
        self,
        telegram_user_id: int,
        telegram_payment_charge_id: str,
        *,
        is_canceled: bool,
    ) -> None:
        try:
            accepted = await self._bot.edit_user_star_subscription(
                telegram_user_id,
                telegram_payment_charge_id,
                is_canceled,
                request_timeout=self._timeout,
            )
        except TelegramBadRequest as exc:
            raise PermanentProviderError("telegram_stars_subscription_rejected") from exc
        except TelegramAPIError as exc:
            raise UnknownProviderOutcomeError("telegram_stars_subscription_unknown") from exc
        if not accepted:
            raise UnknownProviderOutcomeError("telegram_stars_subscription_unknown")

    async def _try_reconcile(
        self,
        charge_id: str,
        telegram_user_id: int,
        expected_amount: int,
    ) -> AuthoritativeRefund | None:
        try:
            found = await self._find_refund(charge_id, telegram_user_id)
        except TelegramAPIError:
            return None
        if found is None:
            return None
        amount, _ = found
        if amount != expected_amount:
            raise PermanentProviderError("telegram_stars_refund_amount_mismatch")
        return self._fact(charge_id, amount)

    async def _find_refund(
        self,
        charge_id: str,
        telegram_user_id: int | None = None,
    ) -> tuple[int, int] | None:
        page_size = 100
        for page in range(self._pages):
            result = await self._bot.get_star_transactions(
                offset=page * page_size,
                limit=page_size,
                request_timeout=self._timeout,
            )
            for transaction in result.transactions:
                receiver = transaction.receiver
                if transaction.id != charge_id or not isinstance(receiver, TransactionPartnerUser):
                    continue
                if receiver.transaction_type != "invoice_payment":
                    continue
                if telegram_user_id is not None and receiver.user.id != telegram_user_id:
                    continue
                if transaction.nanostar_amount not in {None, 0}:
                    raise PermanentProviderError("telegram_stars_refund_fractional_amount")
                return abs(transaction.amount), receiver.user.id
            if len(result.transactions) < page_size:
                return None
        # The scan is bounded on purpose, so exhausting it is not proof of absence: the caller
        # keeps the reservation and retries, and this is the only signal that the window is
        # too small for the current transaction volume.
        logger.warning(
            "telegram_stars_refund_scan_exhausted pages=%s page_size=%s",
            self._pages,
            page_size,
        )
        return None

    @staticmethod
    def _fact(charge_id: str, amount: int) -> AuthoritativeRefund:
        return AuthoritativeRefund(
            provider=TELEGRAM_STARS_PROVIDER,
            # Telegram deliberately reuses the original transaction ID for the outgoing
            # refund. The ledger needs a distinct external identity for the reversal.
            provider_refund_id=f"{_REFUND_ID_PREFIX}{charge_id}",
            provider_payment_id=charge_id,
            status="succeeded",
            amount_minor=amount,
            currency=TELEGRAM_STARS_CURRENCY,
            provider_status="refunded",
            live_mode=True,
        )


def _charge_id_from_refund_id(refund_id: str) -> str | None:
    if not refund_id.startswith(_REFUND_ID_PREFIX):
        return None
    value = refund_id.removeprefix(_REFUND_ID_PREFIX)
    return value or None
