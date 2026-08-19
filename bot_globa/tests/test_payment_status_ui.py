from app.bot import core_handlers
from app.bot.commands import BOT_COMMANDS
from app.bot.payment_status_handlers import _status_copy, balance_with_payment_status
from app.services.payment_status_service import PaymentStatusView
from datetime import UTC, datetime
from uuid import UUID


def _view(status: str, failure_code: str | None = None, *, requested: bool = False) -> PaymentStatusView:
    return PaymentStatusView(
        order_id=UUID("00000000-0000-0000-0000-000000000123"),
        provider="yookassa",
        product_code="reading_single",
        status=status,
        failure_code=failure_code,
        created_at=datetime.now(UTC),
        reconciliation_requested=requested,
    )


def test_active_balance_refresh_uses_provider_backed_status_handler() -> None:
    callbacks = [handler.callback for handler in core_handlers.router.callback_query.handlers]

    assert core_handlers.balance_screen not in callbacks
    assert balance_with_payment_status in callbacks
    assert callbacks.count(balance_with_payment_status) == 1


def test_payment_status_copy_distinguishes_recovery_and_manual_review() -> None:
    assert "Проверка последней оплаты запущена" in _status_copy(
        _view("pending", requested=True)
    )
    assert "ещё проверяется" in _status_copy(_view("pending"))
    manual = _status_copy(_view("manual_review", "amount_mismatch"))
    assert "ручной проверки" in manual
    assert "amount_mismatch" in manual
    assert "зачислена" in _status_copy(_view("completed"))


def test_payment_commands_remain_available() -> None:
    commands = {item.command for item in BOT_COMMANDS}
    assert {"pay", "paysupport"} <= commands
