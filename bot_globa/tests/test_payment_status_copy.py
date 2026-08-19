from datetime import UTC, datetime
from uuid import UUID

from app.bot.payment_status_handlers import _status_copy
from app.services.payment_status_service import PaymentStatusView


def _view(
    status: str, failure_code: str | None = None, *, requested: bool = False
) -> PaymentStatusView:
    return PaymentStatusView(
        order_id=UUID("00000000-0000-0000-0000-000000000123"),
        provider="yookassa",
        product_code="reading_single",
        status=status,
        failure_code=failure_code,
        created_at=datetime.now(UTC),
        reconciliation_requested=requested,
    )


def test_payment_status_copy_distinguishes_recovery_and_manual_review() -> None:
    requested = _status_copy(_view("pending", requested=True))
    waiting = _status_copy(_view("pending"))
    assert requested.startswith("\n\n🔄")
    assert waiting.startswith("\n\n⏳")
    assert "Проверяем последнюю оплату" in requested
    assert "Проверяем последнюю оплату" in waiting
    assert "Это может занять несколько секунд" in requested
    assert "Это может занять несколько секунд" in waiting
    manual = _status_copy(_view("manual_review", "amount_mismatch"))
    assert "ручной проверки" in manual
    assert "amount_mismatch" in manual
    assert "зачислена" in _status_copy(_view("completed"))
