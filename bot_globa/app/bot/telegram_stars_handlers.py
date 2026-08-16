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
from app.bot.keyboards import payment_methods_back_button, payment_success_keyboard
from app.bot.scene_media import Scene
from app.bot.screen import show_screen
from app.config import Settings
from app.services.credits_service import CreditsService
from app.services.onboarding import OnboardingService
from app.services.telegram_stars_service import (
    TelegramStarsInvoice,
    TelegramStarsPaymentFact,
    TelegramStarsPaymentService,
    TelegramStarsRejectedError,
    TelegramStarsStateError,
)

router = Router(name="telegram_stars")
_PAYMENT_RESUME_KEY = "payment_resume_callback"


def payment_terms_text(settings: Settings) -> str:
    """Return clear purchase terms without depending on an external web page."""
    return (
        "Условия оплаты\n\n"
        f"• {texts.BRAND_NAME} продаёт доступ к цифровым полным разборам и подписке. "
        "Это развлекательный и "
        "рефлексивный сервис, а не медицинская, юридическая или финансовая консультация.\n"
        "• Состав покупки и окончательная цена в ⭐ показываются до подтверждения платежа.\n"
        "• Доступ открывается только после успешного подтверждения Telegram. Если он задержался, "
        "не платите повторно — откройте /paysupport.\n"
        "• Подписка продлевается каждые 30 дней, пока вы её не отмените. Отмена отключает "
        "следующее продление, но сохраняет уже оплаченный период.\n"
        f"• Команда /refund покажет, доступен ли полный возврат в течение "
        f"{settings.billing_refund_window_days} дней. Он возможен только для подходящей покупки, "
        "если оплаченные разборы не были использованы.\n\n"
        "Оплачивая счёт, вы подтверждаете, что прочитали и принимаете эти условия."
    )


def payment_support_text() -> str:
    """Return self-service payment support guidance directly in Telegram."""
    return (
        "Поддержка по платежам\n\n"
        "• Звёзды списаны, а доступ к оплаченным разборам ещё не появился: не платите повторно. "
        "Откройте «Покупки» через меню бота и обновите доступ.\n"
        "• Бот сообщил о ручной сверке: повторная оплата не нужна. Сохраните сообщение-чек "
        "Telegram до завершения сверки.\n"
        "• Возврат: откройте /refund. Статус уже созданного запроса — /refund_status.\n"
        "• Telegram Support не обрабатывает покупки в этом боте; вопросы по ним нужно "
        "решать через команды бота."
    )


def _invoice_description(invoice: TelegramStarsInvoice) -> str:
    """Keep Telegram's native invoice customer-facing; credits are only an internal ledger."""

    if invoice.subscription_period is not None:
        suffix = " Оплаченный период — 30 дней; автопродление можно отключить."
    else:
        suffix = " Доступ к покупке откроется после подтверждения Telegram."
    return f"{invoice.title}.{suffix}"[:255]


def _payment_methods_keyboard(product_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[payment_methods_back_button(product_code)]])


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
            reply_markup=_payment_methods_keyboard(product_code),
            state=state,
        )
        return

    description = _invoice_description(invoice)
    if invoice.subscription_period is not None:
        link = await bot.create_invoice_link(
            title=invoice.title,
            description=description,
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
                    [payment_methods_back_button(product_code)],
                ]
            ),
            state=state,
        )
        return

    await show_screen(
        callback.message,
        Scene.CHECKOUT,
        f"Счёт на {invoice.amount} ⭐ откроется следующим сообщением. "
        "Доступ откроется только после подтверждения Telegram. "
        "До оплаты прочитайте /terms; подтверждая счёт, вы принимаете условия.",
        reply_markup=_payment_methods_keyboard(product_code),
        state=state,
    )
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=invoice.title,
        description=description,
        payload=invoice.payload,
        currency="XTR",
        prices=[LabeledPrice(label=invoice.price_label, amount=invoice.amount)],
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"Оплатить {invoice.amount} ⭐", pay=True)],
                [payment_methods_back_button(product_code)],
            ]
        ),
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
    data = await state.get_data()
    resume = data.get(_PAYMENT_RESUME_KEY)
    await show_screen(
        message,
        Scene.SUBSCRIPTION_ACTIVE if completed.subscription else Scene.BALANCE,
        "Подписка активна." if completed.subscription else "Оплата подтверждена.",
        reply_markup=payment_success_keyboard(resume if isinstance(resume, str) else None),
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
