"""Domain-neutral Telegram onboarding, account, privacy and credit routes."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import texts
from app.bot.keyboards import (
    age_keyboard,
    checkout_creating_keyboard,
    checkout_keyboard,
    consent_keyboard,
    main_menu_keyboard,
    payment_market_keyboard,
    privacy_confirmation_keyboard,
    privacy_keyboard,
    products_keyboard,
    receipt_contact_keyboard,
)
from app.bot.states import OnboardingStates, PaymentStates
from app.config import Settings
from app.domain.products import ProductCatalog
from app.services.checkout_service import CheckoutRejectedError, CheckoutService
from app.services.credits_service import CreditsService
from app.services.data_deletion import DataDeletionService
from app.services.onboarding import (
    CURRENT_CONSENT_VERSION,
    OnboardingService,
    OnboardingStep,
    TelegramIdentity,
)
from app.services.payment_service import CheckoutOutcome, PaymentService
from app.services.receipt_contact import InvalidReceiptContactError, validate_receipt_contact

router = Router(name="oracle_core")


def _identity(callback: CallbackQuery) -> TelegramIdentity:
    telegram_user = callback.from_user
    return TelegramIdentity(
        telegram_user_id=telegram_user.id,
        username=telegram_user.username,
        first_name=telegram_user.first_name,
        language=telegram_user.language_code,
    )


async def _show_onboarding_step(message: Message, state: FSMContext, step: OnboardingStep) -> None:
    if step is OnboardingStep.AGE:
        await state.set_state(OnboardingStates.waiting_for_age)
        await message.answer(texts.WELCOME, reply_markup=age_keyboard())
        return
    if step is OnboardingStep.CONSENT:
        await state.set_state(OnboardingStates.waiting_for_consent)
        await message.answer(
            texts.CONSENT.format(version=CURRENT_CONSENT_VERSION),
            reply_markup=consent_keyboard(),
        )
        return
    await state.clear()
    await message.answer(texts.MAIN_MENU, reply_markup=main_menu_keyboard())


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, onboarding: OnboardingService) -> None:
    """Enter the oracle product without reviving legacy relationship-analysis drafts."""

    if message.from_user is None:
        return
    telegram_user = message.from_user
    _, step = await onboarding.start(
        TelegramIdentity(
            telegram_user_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            language=telegram_user.language_code,
        )
    )
    await _show_onboarding_step(message, state, step)


@router.callback_query(F.data == "onboarding:age:no")
async def decline_age(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(texts.AGE_DECLINED)


@router.callback_query(F.data == "onboarding:age:yes")
async def confirm_age(
    callback: CallbackQuery, state: FSMContext, onboarding: OnboardingService
) -> None:
    if await onboarding.current_step(callback.from_user.id) is OnboardingStep.AGE:
        await onboarding.start(_identity(callback))
    step = await onboarding.confirm_age(callback.from_user.id)
    await callback.answer()
    if isinstance(callback.message, Message):
        await _show_onboarding_step(callback.message, state, step)


@router.callback_query(F.data == "onboarding:consent")
async def accept_consent(
    callback: CallbackQuery, state: FSMContext, onboarding: OnboardingService
) -> None:
    if await onboarding.current_step(callback.from_user.id) is OnboardingStep.AGE:
        await onboarding.start(_identity(callback))
    step = await onboarding.accept_consent(callback.from_user.id)
    await callback.answer()
    if isinstance(callback.message, Message):
        await _show_onboarding_step(callback.message, state, step)


@router.callback_query(F.data.in_({"report:menu", "menu:home"}))
async def return_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Keep historical generic menu callbacks harmless during the migration."""

    await callback.answer()
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.answer(texts.MAIN_MENU, reply_markup=main_menu_keyboard())


@router.callback_query(F.data == "menu:privacy")
async def privacy_screen(callback: CallbackQuery, privacy_retention_days: int) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            texts.PRIVACY_INFO.format(days=privacy_retention_days),
            reply_markup=privacy_keyboard(),
        )


@router.callback_query(F.data == "privacy:delete_all")
async def delete_all_prompt(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            texts.DELETE_ALL_PROMPT,
            reply_markup=privacy_confirmation_keyboard(),
        )


@router.callback_query(F.data.in_({"privacy:cancel", "privacy:menu"}))
async def delete_all_cancel(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            texts.DELETE_ALL_CANCELLED if callback.data == "privacy:cancel" else texts.MAIN_MENU,
            reply_markup=main_menu_keyboard(),
        )


@router.callback_query(F.data == "privacy:confirm_all")
async def delete_all_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    data_deletion: DataDeletionService,
) -> None:
    user = await onboarding.current_user(callback.from_user.id)
    if user is not None:
        await data_deletion.delete_account(user.id)
    await state.clear()
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(texts.DELETE_ALL_DONE)


@router.callback_query(F.data.in_({"menu:balance", "credits:refresh"}))
async def balance_screen(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    credits: CreditsService,
    catalog: ProductCatalog,
    billing_settings: Settings,
) -> None:
    await callback.answer()
    user = await onboarding.current_user(callback.from_user.id)
    if user is None or not isinstance(callback.message, Message):
        return
    balance = await credits.balance(user.id)
    await callback.message.answer(
        f"Ваш баланс: {balance} кредитов\n"
        f"Полный персональный разбор: от {billing_settings.reading_full_price_credits} кредита.\n\n"
        "Выберите пакет или продукт:",
        reply_markup=products_keyboard(catalog),
    )


def _callback_parts(callback: CallbackQuery) -> list[str]:
    return (callback.data or "").split(":")


@router.callback_query(F.data.startswith("credits:buy:"))
async def buy_credits(
    callback: CallbackQuery,
    onboarding: OnboardingService,
    payments: PaymentService | None,
    billing_settings: Settings,
) -> None:
    await callback.answer()
    user = await onboarding.current_user(callback.from_user.id)
    if user is None or not isinstance(callback.message, Message):
        return
    product_code = _callback_parts(callback)[-1]
    if payments is None or billing_settings.billing_enabled:
        await callback.message.answer(
            "Выберите регион и валюту оплаты.",
            reply_markup=payment_market_keyboard(product_code),
        )
        return
    outcome = await payments.create_checkout(user.id, product_code)
    if outcome.outcome is CheckoutOutcome.CREATING:
        await callback.message.answer(
            "Тестовая оплата уже создаётся. Обновите экран через несколько секунд.",
            reply_markup=checkout_creating_keyboard(product_code),
        )
        return
    if (
        outcome.outcome not in {CheckoutOutcome.CREATED, CheckoutOutcome.EXISTING}
        or outcome.checkout is None
    ):
        await callback.message.answer("Не удалось создать тестовую оплату.")
        return
    await callback.message.answer(
        "Тестовая оплата — реальные деньги не списываются.",
        reply_markup=checkout_keyboard(outcome.checkout.url),
    )


@router.callback_query(F.data.startswith("credits:offer:"))
async def create_production_checkout(
    callback: CallbackQuery,
    state: FSMContext,
    onboarding: OnboardingService,
    checkout: CheckoutService,
    billing_settings: Settings,
) -> None:
    await callback.answer()
    user = await onboarding.current_user(callback.from_user.id)
    if user is None or not isinstance(callback.message, Message):
        return
    parts = _callback_parts(callback)
    if len(parts) != 5:
        await callback.message.answer("Этот вариант оплаты недоступен.")
        return
    _, _, product_code, market, currency = parts
    if billing_settings.yookassa_receipts_required and market == "RU" and currency == "RUB":
        await state.set_state(PaymentStates.waiting_for_receipt_contact)
        await state.set_data({"product_code": product_code, "market": market, "currency": currency})
        await callback.message.answer(
            "Отправьте email или телефон в международном формате для кассового чека.",
            reply_markup=receipt_contact_keyboard(),
        )
        return
    try:
        result = await checkout.create_one_time_checkout(user.id, product_code, market, currency)
    except CheckoutRejectedError:
        await callback.message.answer("Оплата сейчас недоступна. Попробуйте позже.")
        return
    if not result.url:
        await callback.message.answer(
            "Оплата создаётся. Попробуйте обновить через несколько секунд."
        )
        return
    await callback.message.answer(
        "Откройте защищённую страницу платёжного провайдера.",
        reply_markup=checkout_keyboard(result.url),
    )


@router.message(PaymentStates.waiting_for_receipt_contact)
async def receive_receipt_contact(
    message: Message,
    state: FSMContext,
    onboarding: OnboardingService,
    checkout: CheckoutService,
) -> None:
    data = await state.get_data()
    if message.from_user is None or not message.text:
        await state.clear()
        await message.answer("Контакт для чека не получен. Оплата отменена.")
        return
    try:
        contact = validate_receipt_contact(message.text)
        product_code = str(data["product_code"])
        market = str(data["market"])
        currency = str(data["currency"])
        user = await onboarding.current_user(message.from_user.id)
        if user is None:
            raise CheckoutRejectedError("user not found")
        result = await checkout.create_one_time_checkout(
            user.id,
            product_code,
            market,
            currency,
            receipt_contact=contact.value,
        )
    except InvalidReceiptContactError:
        await message.answer(
            "Некорректный email или телефон. Проверьте формат и отправьте ещё раз.",
            reply_markup=receipt_contact_keyboard(),
        )
        return
    except (CheckoutRejectedError, KeyError):
        await state.clear()
        await message.answer("Оплата сейчас недоступна. Попробуйте позже.")
        return
    await state.clear()
    if result.url:
        await message.answer(
            "Откройте защищённую страницу платёжного провайдера.",
            reply_markup=checkout_keyboard(result.url),
        )
    else:
        await message.answer("Оплата создаётся. Попробуйте обновить через несколько секунд.")


@router.callback_query(F.data == "credits:receipt:cancel")
async def cancel_receipt_contact(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer("Оплата отменена.", reply_markup=main_menu_keyboard())
