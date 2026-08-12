"""Telegram-native Stars checkout, completion, and support routes."""

from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    BotSubscriptionUpdated,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from app.bot.scene_media import Scene, answer_scene
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


@router.callback_query(F.data.startswith("credits:stars:"))
async def create_stars_invoice(
    callback: CallbackQuery,
    bot: Bot,
    onboarding: OnboardingService,
    telegram_stars: TelegramStarsPaymentService,
) -> None:
    await callback.answer()
    user = await onboarding.current_user(callback.from_user.id)
    if user is None or not isinstance(callback.message, Message):
        return
    product_code = (callback.data or "").removeprefix("credits:stars:")
    try:
        invoice = await telegram_stars.create_invoice(user.id, product_code)
    except TelegramStarsRejectedError:
        await answer_scene(
            callback.message,
            Scene.CHECKOUT_UNAVAILABLE,
            "Оплата звёздами сейчас недоступна. Попробуйте позже.",
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
        await answer_scene(
            callback.message,
            Scene.SUBSCRIPTION_CHECKOUT,
            f"Подписка стоит {invoice.amount} ⭐ каждые 30 дней. "
            "Telegram покажет условия автопродления до подтверждения.",
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
        )
        return

    await answer_scene(
        callback.message,
        Scene.CHECKOUT,
        f"Счёт на {invoice.amount} ⭐ откроется следующим сообщением. "
        "Кредиты начислятся только после подтверждения Telegram.",
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
        await answer_scene(
            message,
            Scene.CHECKOUT_UNAVAILABLE,
            "Платёж получен, но требует ручной сверки. Откройте /paysupport — "
            "повторно платить не нужно.",
        )
        return
    if completed.outcome not in {"completed", "already_completed"}:
        await answer_scene(
            message,
            Scene.CHECKOUT_UNAVAILABLE,
            "Платёж получен и передан на сверку. Откройте /paysupport — повторно платить не нужно.",
        )
        return
    user = await onboarding.current_user(message.from_user.id)
    balance = None if user is None else await credits.balance(user.id)
    balance_copy = "" if balance is None else f" Текущий баланс: {balance} кредитов."
    await answer_scene(
        message,
        Scene.SUBSCRIPTION_ACTIVE if completed.subscription else Scene.BALANCE,
        f"Оплата {completed.credits} кредитов подтверждена.{balance_copy}",
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
    url = billing_settings.billing_terms_url
    text = f"Условия покупок и подписок: {url}" if url else "Условия сейчас недоступны."
    await message.answer(text)


@router.message(Command("paysupport"))
async def stars_payment_support(message: Message, billing_settings: Settings) -> None:
    url = billing_settings.billing_support_url
    text = (
        "Поддержка по платежам и возвратам: " + url
        if url
        else "Поддержка по платежам сейчас недоступна."
    )
    await message.answer(text)
