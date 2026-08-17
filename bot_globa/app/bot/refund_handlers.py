"""Telegram payment navigation and safe monetary refund requests."""

from decimal import Decimal
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.consent import ensure_consent
from app.bot.keyboards import products_keyboard
from app.bot.scene_media import Scene
from app.bot.screen import send_artifact, show_screen
from app.config import Settings
from app.domain.billing import BillingCatalog
from app.services.credits_service import CreditsService
from app.services.onboarding import OnboardingService, TelegramIdentity
from app.services.refund_service import (
    RefundPurchaseView,
    RefundRequestOutcome,
    RefundService,
    RefundView,
)

router = Router(name="refunds")

_STATUS_LABELS = {
    "requested": "запрошен",
    "credits_reserved": "доступ зарезервирован",
    "provider_pending": "обрабатывается платёжной системой",
    "succeeded": "деньги возвращены",
    "failed": "возврат отклонён",
    "manual_review": "нужна ручная проверка",
}
_PRODUCT_LABELS = {
    "reading_single": "Один полный разбор",
    "reading_pack_5": "Пакет полных разборов",
    "subscription_monthly": "Подписка",
    "astrology_natal": "Натальный разбор",
    "astrology_forecast": "Астрологический прогноз",
}


def _money(amount_minor: int, currency: str) -> str:
    if currency == "XTR":
        return f"{amount_minor} ⭐"
    return f"{Decimal(amount_minor) / Decimal(100):.2f} {currency}"


def _purchase_label(product_code: str) -> str:
    return _PRODUCT_LABELS.get(product_code, "Покупка")


def _purchase_keyboard(rows: tuple[RefundPurchaseView, ...]) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=(
                    f"{_purchase_label(row.product_code)} · "
                    f"{_money(row.refund_amount_minor, row.currency)}"
                ),
                callback_data=(f"refund:request:{row.payment_order_id}:{row.refundable_credits}"),
            )
        ]
        for row in rows
    ]
    buttons.append([InlineKeyboardButton(text="История возвратов", callback_data="refund:history")])
    buttons.append([InlineKeyboardButton(text="Вернуться", callback_data="menu:balance")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _history_text(rows: tuple[RefundView, ...]) -> str:
    if not rows:
        return "У вас пока нет запросов на возврат."
    lines = ["Последние возвраты:"]
    for row in rows:
        label = _STATUS_LABELS.get(row.status, row.status)
        lines.append(f"• {_money(row.amount_minor, row.currency)} · {label}")
    return "\n".join(lines)


def _message_identity(message: Message) -> TelegramIdentity | None:
    telegram_user = message.from_user
    if telegram_user is None:
        return None
    return TelegramIdentity(
        telegram_user_id=telegram_user.id,
        username=telegram_user.username,
        first_name=telegram_user.first_name,
        language=telegram_user.language_code,
    )


@router.message(Command("pay"))
async def payment_menu(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    credits: CreditsService,
    billing_catalog: BillingCatalog,
    billing_settings: Settings,
    privacy_retention_days: int,
) -> None:
    """Open the existing purchase catalogue from Telegram's command menu."""

    identity = _message_identity(message)
    if identity is None:
        return
    if not await ensure_consent(
        message,
        identity.telegram_user_id,
        state,
        onboarding,
        privacy_retention_days,
        identity=identity,
    ):
        return
    user = await onboarding.current_user(identity.telegram_user_id)
    if user is None:
        return
    balance = await credits.balance(user.id)
    await show_screen(
        message,
        Scene.BALANCE,
        f"Доступно полных разборов: "
        f"{balance // billing_settings.reading_full_price_credits}.\n\n"
        "Выберите вариант:",
        reply_markup=products_keyboard(billing_catalog, billing_settings),
        state=state,
    )


@router.message(Command("refund"))
async def refund_menu(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    refunds: RefundService | None,
) -> None:
    if refunds is None or message.from_user is None:
        await show_screen(
            message, Scene.REFUND_UNAVAILABLE, "Возвраты сейчас недоступны.", state=state
        )
        return
    user = await onboarding.current_user(message.from_user.id)
    if user is None:
        await show_screen(
            message, Scene.REFUND_UNAVAILABLE, "Возвраты сейчас недоступны.", state=state
        )
        return
    purchases = await refunds.eligible_purchases(user.id)
    if not purchases:
        await show_screen(
            message,
            Scene.REFUND_UNAVAILABLE,
            "Сейчас нет покупок, подходящих для автоматического возврата. "
            "Для возврата нужна неиспользованная часть покупки в пределах срока политики.",
            state=state,
        )
        return
    await show_screen(
        message,
        Scene.REFUND_AVAILABLE,
        "Выберите покупку. После подтверждения неиспользованная часть покупки будет "
        "зарезервирована до окончательного ответа платёжной системы.\n\n"
        "Важно: возврат платежа за подписку не отключает будущие продления. "
        "Автопродление управляется отдельно в разделе подписки.",
        reply_markup=_purchase_keyboard(purchases),
        state=state,
    )


@router.message(Command("refund_status"))
async def refund_status_command(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    refunds: RefundService | None,
) -> None:
    if refunds is None or message.from_user is None:
        await show_screen(
            message, Scene.REFUND_HISTORY, "История возвратов сейчас недоступна.", state=state
        )
        return
    user = await onboarding.current_user(message.from_user.id)
    if user is None:
        await show_screen(
            message, Scene.REFUND_HISTORY, "История возвратов сейчас недоступна.", state=state
        )
        return
    await show_screen(
        message, Scene.REFUND_HISTORY, _history_text(await refunds.history(user.id)), state=state
    )


@router.callback_query(F.data == "refund:history")
async def refund_history_callback(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    refunds: RefundService | None,
) -> None:
    await callback.answer()
    user = await onboarding.current_user(callback.from_user.id)
    if user is None or refunds is None or not isinstance(callback.message, Message):
        return
    await show_screen(
        callback.message,
        Scene.REFUND_HISTORY,
        _history_text(await refunds.history(user.id)),
        state=state,
    )


@router.callback_query(F.data.startswith("refund:request:"))
async def request_refund_callback(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    refunds: RefundService | None,
) -> None:
    user = await onboarding.current_user(callback.from_user.id)
    parts = (callback.data or "").split(":")
    try:
        order_id = UUID(parts[2])
        credit_units = int(parts[3])
    except (IndexError, ValueError):
        await callback.answer("Некорректный запрос.", show_alert=True)
        return
    if user is None or refunds is None:
        await callback.answer("Возвраты сейчас недоступны.", show_alert=True)
        return
    result = await refunds.request_refund(user.id, order_id, credit_units)
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if result.outcome is RefundRequestOutcome.CREATED and result.refund is not None:
        await send_artifact(
            callback.message,
            Scene.REFUND_ACCEPTED,
            "Запрос принят. Неиспользованный доступ зарезервирован; "
            f"сумма возврата — {_money(result.refund.amount_minor, result.refund.currency)}. "
            "Статус можно проверить командой /refund_status.",
            state=state,
        )
        return
    messages = {
        RefundRequestOutcome.DISABLED: "Возвраты временно отключены.",
        RefundRequestOutcome.NOT_FOUND: "Пользователь или покупка не найдены.",
        RefundRequestOutcome.NOT_ELIGIBLE: (
            "Эта покупка не подходит для автоматического возврата."
        ),
        RefundRequestOutcome.INVALID_UNITS: (
            "Состав доступного возврата изменился. Откройте /refund заново."
        ),
        RefundRequestOutcome.INSUFFICIENT_CREDITS: (
            "Часть оплаченного доступа уже использована, поэтому автоматический возврат невозможен."
        ),
        RefundRequestOutcome.PARTIAL_UNSUPPORTED: (
            "Для этой покупки доступен только полный возврат."
        ),
        RefundRequestOutcome.ALREADY_PENDING: (
            "По этой покупке уже есть незавершённый запрос на возврат."
        ),
    }
    await show_screen(
        callback.message,
        Scene.REFUND_UNAVAILABLE,
        messages.get(result.outcome, "Возврат не удалось создать."),
        state=state,
    )
