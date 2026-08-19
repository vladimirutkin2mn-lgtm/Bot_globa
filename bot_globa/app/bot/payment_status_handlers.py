"""Payment recovery UX: make “Обновить доступ” actually verify pending payments."""

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import core_handlers
from app.bot.consent import ensure_consent
from app.bot.keyboards import products_keyboard
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.config import Settings
from app.domain.billing import BillingCatalog
from app.services.credits_service import CreditsService
from app.services.onboarding import OnboardingService
from app.services.payment_status_service import PaymentStatusService, PaymentStatusView

_INSTALL_MARKERS: set[str] = set()


def _status_copy(view: PaymentStatusView | None) -> str:
    if view is None:
        return ""
    if view.status == "completed":
        return "\n\n✅ Последняя оплата зачислена."
    if view.status in {"creating", "pending"}:
        if view.reconciliation_requested:
            return (
                "\n\n🔄 Проверка последней оплаты запущена у платёжного провайдера. "
                "Доступ появится только после подтверждения оплаты."
            )
        return (
            "\n\n⏳ Последняя оплата ещё проверяется. "
            "Numa не начисляет доступ, пока провайдер не подтвердит платёж."
        )
    if view.status == "manual_review":
        suffix = f" Код: {view.failure_code}." if view.failure_code else ""
        return "\n\n⚠️ Последняя оплата требует ручной проверки." + suffix
    if view.status in {"failed", "cancelled"}:
        return "\n\n❌ Последняя попытка оплаты не была подтверждена провайдером."
    return f"\n\nСтатус последней оплаты: {view.status}."


async def balance_with_payment_status(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    credits: CreditsService,
    billing_catalog: BillingCatalog,
    billing_settings: Settings,
    payment_status: PaymentStatusService,
    privacy_retention_days: int,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if not await ensure_consent(
        callback.message,
        callback.from_user.id,
        state,
        onboarding,
        privacy_retention_days,
        identity=core_handlers._identity(callback),
    ):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        return
    payment = (
        await payment_status.refresh(user.id)
        if callback.data == "credits:refresh"
        else await payment_status.latest(user.id)
    )
    balance = await credits.balance(user.id)
    resume = core_handlers._stored_resume(await state.get_data())
    await show_screen(
        callback.message,
        Scene.BALANCE,
        (
            f"Доступно глубоких разборов: "
            f"{balance // billing_settings.reading_full_price_credits}."
            f"{_status_copy(payment)}\n\n"
            "Выберите вариант:"
        ),
        reply_markup=products_keyboard(
            billing_catalog,
            billing_settings,
            resume_callback=resume,
        ),
        state=state,
    )


def install_payment_status_handlers() -> None:
    """Replace the passive balance refresh with provider-backed recovery scheduling."""

    if "payment_status" in _INSTALL_MARKERS:
        return
    router = core_handlers.router
    router.callback_query.handlers[:] = [
        handler
        for handler in router.callback_query.handlers
        if handler.callback is not core_handlers.balance_screen
    ]
    router.callback_query(F.data.in_({"menu:balance", "credits:refresh"}))(
        balance_with_payment_status
    )
    _INSTALL_MARKERS.add("payment_status")
