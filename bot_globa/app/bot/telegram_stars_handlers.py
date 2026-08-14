"""Telegram-native Stars checkout, completion, and support routes."""

from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BotSubscriptionUpdated,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from app.bot import texts
from app.bot.consent import ensure_consent
from app.bot.keyboards import main_menu_keyboard
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.config import Settings
from app.services.credits_service import CreditsService
from app.services.onboarding import OnboardingService
from app.services.telegram_stars_service import (
    TelegramStarsPaymentFact,
    TelegramStarsPaymentService,
    TelegramStarsRejectedError,
    TelegramStarsStateError,
)

router = Router(name="telegram_stars")


def payment_terms_text(settings: Settings) -> str:
    """Return clear purchase terms without depending on an external web page."""
    return (
        "Условия оплаты\n\n"
        f"• {texts.BRAND_NAME} продаёт цифровые кредиты для функций бота. "
        "Это развлекательный и "
        "рефлексивный сервис, а не медицинская, юридическая или финансовая консультация.\n"
        "• Состав покупки и окончательная цена в ⭐ показываются до подтверждения платежа.\n"
        "• Кредиты начисляются только после успешного подтверждения Telegram. Если начисление "
        "задержалось, не платите повторно — откройте /paysupport.\n"
        "• Подписка продлевается каждые 30 дней, пока вы её не отмените. Отмена отключает "
        "следующее продление, но сохраняет уже оплаченный период.\n"
        f"• Команда /refund покажет, доступен ли полный возврат в течение "
        f"{settings.billing_refund_window_days} дней. Он возможен только для подходящей покупки, "
        "если выданные за неё кредиты не использованы.\n\n"
        "Оплачивая счёт, вы подтверждаете, что прочитали и принимаете эти условия."
    )


def payment_support_text() -> str:
    """Return self-service payment support guidance directly in Telegram."""
    return (
        "Поддержка по платежам\n\n"
        "• Звёзды списаны, а кредиты ещё не появились: не платите повторно. Обновите экран "
        "баланса через меню бота.\n"
        "• Бот сообщил о ручной сверке: повторная оплата не нужна. Сохраните сообщение-чек "
        "Telegram до завершения сверки.\n"
        "• Возврат: откройте /refund. Статус уже созданного запроса — /refund_status.\n"
        "• Telegram Support не обрабатывает покупки в этом боте; вопросы по ним нужно "
        "решать через команды бота."
    )


@router.callback_query(F.data.startswith("credits:stars:"))
async def create_stars_invoice(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    onboarding: OnboardingService,
    telegram_stars: TelegramStarsPaymentService,
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
    ):
        return
    user = await onboarding.current_user(callback.from_user.id)
    if user is None:
        return
    product_code = (callback.data or "").removeprefix("credits:stars:")
    try:
        invoice = await telegram_stars.create_invoice(user.id, product_code)
    except TelegramStarsRejectedError:
        await show_screen(
            callback.message,
            Scene.CHECKOUT_UNAVAILABLE,
            "Оплата звёздами сейчас недоступна. Попробуйте позже.",
            state=state,
        )
        return

    if invoice.subscription_period is not None:
        link = await bot.create_invoice_link(
            title=invoice.title,
            description=invoice.description,
            payload=invoice.payload,
            currency="XTR",
            prices=[LabeledPrice(label=invoice.price_label, amount=invoice.amount)],
            subscription_period=invoice.subscription_period,
        )
        await show_screen(
            callback.message,
            Scene.SUBSCRIPTION_CHECKOUT,
            f"Подписка стоит {invoice.amount} ⭐ каждые 30 дней. "
            "Telegram покажет условия автопродления до подтверждения. "
            "До оплаты прочитайте /terms; подтверждая счёт, вы принимаете условия.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"Оплатить {invoice.amount} ⭐", url=link)],
                    [
                        InlineKeyboardButton(
                            text="Вернуться", callback_data="credits:buy:subscription_monthly"
                        )
                    ],
                ]
            ),
            state=state,
        )
        return

    await show_screen(
        callback.message,
        Scene.CHECKOUT,
        f"Счёт на {invoice.amount} ⭐ откроется следующим сообщлением. "
        "Кредиты начислятся только после подтверждения Telegram. "
        "До оплаты прочитайте /terms; подтверждая счёт, вы принимаете условия.",
        state=state,
    )
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=invoice.title,
        description=invoice.description,
        payload=invoice.payload,
        currency="XTR",
        prices=[LabeledPrice(label=invoice.price_label, amount=invoice.amount)],
    )


@router.pre_checkout_query()
async def approve_stars_checkout(
    query: PreCheckoutQuery,
    telegram_stars: TelegramStarsPaymentService,
) -> None:
    decision = await telegram_stars.validate_pre_checkout(
        query.from_user.id,
        query.id,
        query.invoice_payload,
        query.currency,
        query.total_amount,
    )
    await query.answer(
        ok=decision.approved,
        error_message=decision.error_message if not decision.approved else None,
    )


@router.message(F.successful_payment)
async def complete_stars_payment(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    telegram_stars: TelegramStarsPaymentService,
    credits: CreditsService,
) -> None:
    payment = message.successful_payment
    if message.from_user is None or payment is None or payment.currency != "XTR":
        return
    try:
        completed = await telegram_stars.complete_successful(
            message.from_user.id,
            TelegramStarsPaymentFact(
                currency=payment.currency,
                total_amount=payment.total_amount,
                invoice_payload=payment.invoice_payload,
                telegram_payment_charge_id=payment.telegram_payment_charge_id,
                paid_at=message.date,
                subscription_expiration_date=(
                    datetime.fromtimestamp(payment.subscription_expiration_date, tz=UTC)
                    if payment.subscription_expiration_date is not None
                    else None
                ),
                is_recurring=payment.is_recurring is True,
                is_first_recurring=payment.is_first_recurring is True,
            ),
        )
    except TelegramStarsStateError:
        await show_screen(
            message,
            Scene.CHECKOUT_UNAVAILABLE,
            "Платёж получен, но требует ручной сверки. Откройте /paysupport — "
            "повторно платить не нужно.",
            state=state,
        )
        return
    if completed.outcome not in {"completed", "already_completed"}:
        await show_screen(
            message,
            Scene.CHECKOUT_UNAVAILABLE,
            "Платёж получен и передан на сверку. Откройте /paysupport — повторно платить не нужно.",
            state=state,
        )
        return
    # Keep the service dependency in the handler signature for compatibility with the
    # existing dependency graph, but do not expose the internal credit ledger in UX copy.
    _ = credits
    await show_screen(
        message,
        Scene.SUBSCRIPTION_ACTIVE if completed.subscription else Scene.BALANCE,
        "Подписка активна." if completed.subscription else "Оплата подтверждена.",
        reply_markup=main_menu_keyboard(),
        state=state,
    )


@router.subscription()
async def apply_stars_subscription_update(
    event: BotSubscriptionUpdated,
    telegram_stars: TelegramStarsPaymentService,
) -> None:
    await telegram_stars.apply_subscription_update(
        event.user.id,
        event.invoice_payload,
        event.state,
    )


@router.message(Command("terms"))
async def stars_terms(message: Message, billing_settings: Settings) -> None:
    await message.answer(payment_terms_text(billing_settings))


@router.message(Command("paysupport"))
async def stars_payment_support(message: Message) -> None:
    await message.answer(payment_support_text())
